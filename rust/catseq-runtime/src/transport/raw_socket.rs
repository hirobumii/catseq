//! Linux AF_PACKET transport migrated from CatSeq commit `7c9f02d`.

#[cfg(not(target_os = "linux"))]
use super::{Transport, TransportEnvelope, TransportError, WirePacket};

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct RawSocketConfig {
    pub interface: String,
    pub destination_mac: Option<[u8; 6]>,
}

#[cfg(target_os = "linux")]
mod linux {
    use std::ffi::CString;
    use std::io;
    use std::mem::{size_of, zeroed};
    use std::os::fd::{AsRawFd, FromRawFd, OwnedFd, RawFd};
    use std::time::Instant;

    use crate::model::derive_destination_mac;

    use super::RawSocketConfig;
    use crate::transport::{
        ETHER_TYPE, OASM_PADDING_BYTES, ReceiveError, SendError, Transport, TransportEnvelope,
        TransportError, WirePacket,
    };

    const ETHERNET_HEADER_BYTES: usize = 14;

    #[derive(Debug)]
    pub(crate) struct RawEthernetTransport {
        config: RawSocketConfig,
        descriptor: Option<OwnedFd>,
        envelope: Option<TransportEnvelope>,
    }

    impl RawEthernetTransport {
        pub(crate) const fn new(config: RawSocketConfig) -> Self {
            Self {
                config,
                descriptor: None,
                envelope: None,
            }
        }

        fn descriptor(&self) -> Result<RawFd, TransportError> {
            self.descriptor
                .as_ref()
                .map(AsRawFd::as_raw_fd)
                .ok_or_else(|| TransportError("raw socket is not open".to_owned()))
        }

        fn ethernet_bytes(packet: &WirePacket) -> Vec<u8> {
            let mut bytes = Vec::with_capacity(
                ETHERNET_HEADER_BYTES + OASM_PADDING_BYTES + packet.payload.len(),
            );
            bytes.extend_from_slice(&packet.destination_mac);
            bytes.extend_from_slice(&packet.source_mac);
            bytes.extend_from_slice(&packet.ether_type.to_be_bytes());
            bytes.extend_from_slice(&packet.loopback_marker);
            bytes.extend_from_slice(&[0; OASM_PADDING_BYTES - 8]);
            bytes.extend_from_slice(&packet.payload);
            bytes
        }
    }

    impl Transport for RawEthernetTransport {
        fn open(&mut self) -> Result<TransportEnvelope, TransportError> {
            if self.descriptor.is_some() {
                return self
                    .envelope
                    .ok_or_else(|| TransportError("raw socket has no envelope".to_owned()));
            }
            let interface = CString::new(self.config.interface.as_str())
                .map_err(|_| TransportError("interface name contains NUL".to_owned()))?;
            // SAFETY: `interface` is a valid NUL-terminated C string.
            let interface_index = unsafe { libc::if_nametoindex(interface.as_ptr()) };
            if interface_index == 0 {
                return Err(TransportError(format!(
                    "cannot resolve interface {:?}: {}",
                    self.config.interface,
                    io::Error::last_os_error()
                )));
            }

            // Resolve every envelope fact before creating the privileged raw
            // socket, so MAC overflow cannot happen after an AF_PACKET side effect.
            let source_mac = interface_mac(&interface)?;
            let destination_mac = self.config.destination_mac.map_or_else(
                || {
                    derive_destination_mac(source_mac)
                        .map_err(|error| TransportError(error.to_string()))
                },
                Ok,
            )?;
            let loopback_marker = random_marker()?;
            let envelope = TransportEnvelope {
                ether_type: ETHER_TYPE,
                source_mac,
                destination_mac,
                loopback_marker,
            };

            // SAFETY: syscall arguments are constants and create an owned descriptor.
            let raw_descriptor = unsafe {
                libc::socket(
                    libc::AF_PACKET,
                    libc::SOCK_RAW,
                    i32::from(ETHER_TYPE.to_be()),
                )
            };
            if raw_descriptor < 0 {
                return Err(TransportError(format!(
                    "cannot open AF_PACKET/SOCK_RAW on {:?}: {}",
                    self.config.interface,
                    io::Error::last_os_error()
                )));
            }
            // SAFETY: the successful socket call returned a new descriptor
            // owned by this scope.
            let descriptor = unsafe { OwnedFd::from_raw_fd(raw_descriptor) };
            // SAFETY: zero is a valid initialization for sockaddr_ll.
            let mut address: libc::sockaddr_ll = unsafe { zeroed() };
            address.sll_family = libc::AF_PACKET as u16;
            address.sll_protocol = ETHER_TYPE.to_be();
            address.sll_ifindex = interface_index as i32;
            // SAFETY: pointer and length describe the initialized sockaddr_ll.
            let result = unsafe {
                libc::bind(
                    descriptor.as_raw_fd(),
                    (&raw const address).cast(),
                    size_of::<libc::sockaddr_ll>() as libc::socklen_t,
                )
            };
            if result < 0 {
                let error = io::Error::last_os_error();
                return Err(TransportError(format!(
                    "cannot bind raw socket to {:?}: {error}",
                    self.config.interface
                )));
            }
            self.descriptor = Some(descriptor);
            self.envelope = Some(envelope);
            Ok(envelope)
        }

        fn send(&mut self, packet: &WirePacket) -> Result<(), SendError> {
            let descriptor = self
                .descriptor()
                .map_err(|error| SendError::not_accepted(error.0))?;
            let bytes = Self::ethernet_bytes(packet);
            // SAFETY: buffer is valid for `bytes.len()` and descriptor is open.
            let sent = unsafe { libc::send(descriptor, bytes.as_ptr().cast(), bytes.len(), 0) };
            if sent < 0 {
                let error = io::Error::last_os_error();
                return if error.kind() == io::ErrorKind::WouldBlock {
                    Err(SendError::not_accepted(error.to_string()))
                } else {
                    Err(SendError::acceptance_unknown(error.to_string()))
                };
            }
            if sent as usize != bytes.len() {
                return Err(SendError::acceptance_unknown(format!(
                    "raw socket accepted {sent} of {} bytes",
                    bytes.len()
                )));
            }
            Ok(())
        }

        fn receive(&mut self, deadline: Instant) -> Result<Option<WirePacket>, ReceiveError> {
            let descriptor = self.descriptor().map_err(|error| ReceiveError(error.0))?;
            loop {
                let now = Instant::now();
                if now >= deadline {
                    return Ok(None);
                }
                let remaining = deadline.saturating_duration_since(now);
                let milliseconds = remaining.as_millis().min(i32::MAX as u128) as i32;
                let mut pollfd = libc::pollfd {
                    fd: descriptor,
                    events: libc::POLLIN,
                    revents: 0,
                };
                // SAFETY: pollfd points to one initialized entry.
                let ready = unsafe { libc::poll(&raw mut pollfd, 1, milliseconds.max(1)) };
                if ready == 0 {
                    return Ok(None);
                }
                if ready < 0 {
                    let error = io::Error::last_os_error();
                    if error.kind() == io::ErrorKind::Interrupted {
                        continue;
                    }
                    return Err(ReceiveError(error.to_string()));
                }
                let mut bytes = [0_u8; 2048];
                // SAFETY: destination buffer is writable and descriptor is open.
                let count = unsafe {
                    libc::recv(
                        descriptor,
                        bytes.as_mut_ptr().cast(),
                        bytes.len(),
                        libc::MSG_DONTWAIT,
                    )
                };
                if count < 0 {
                    let error = io::Error::last_os_error();
                    if error.kind() == io::ErrorKind::WouldBlock {
                        continue;
                    }
                    return Err(ReceiveError(error.to_string()));
                }
                let count = count as usize;
                if count < ETHERNET_HEADER_BYTES + OASM_PADDING_BYTES {
                    return Ok(Some(WirePacket {
                        ether_type: if count >= ETHERNET_HEADER_BYTES {
                            u16::from_be_bytes([bytes[12], bytes[13]])
                        } else {
                            0
                        },
                        source_mac: bytes
                            .get(6..12)
                            .and_then(|value| value.try_into().ok())
                            .unwrap_or([0; 6]),
                        destination_mac: bytes
                            .get(..6)
                            .and_then(|value| value.try_into().ok())
                            .unwrap_or([0; 6]),
                        loopback_marker: [0; 8],
                        payload: Vec::new(),
                    }));
                }
                return Ok(Some(WirePacket {
                    destination_mac: bytes[..6].try_into().expect("checked length"),
                    source_mac: bytes[6..12].try_into().expect("checked length"),
                    ether_type: u16::from_be_bytes([bytes[12], bytes[13]]),
                    loopback_marker: bytes[14..22].try_into().expect("checked length"),
                    payload: bytes[ETHERNET_HEADER_BYTES + OASM_PADDING_BYTES..count].to_vec(),
                }));
            }
        }

        fn close(&mut self) {
            drop(self.descriptor.take());
        }
    }

    impl Drop for RawEthernetTransport {
        fn drop(&mut self) {
            self.close();
        }
    }

    fn interface_mac(interface: &CString) -> Result<[u8; 6], TransportError> {
        // SAFETY: syscall arguments are constants and create an owned descriptor.
        let raw_descriptor = unsafe { libc::socket(libc::AF_INET, libc::SOCK_DGRAM, 0) };
        if raw_descriptor < 0 {
            return Err(TransportError(format!(
                "cannot open interface-query socket: {}",
                io::Error::last_os_error()
            )));
        }
        // SAFETY: the successful socket call returned a new descriptor owned
        // by this scope.
        let descriptor = unsafe { OwnedFd::from_raw_fd(raw_descriptor) };
        // SAFETY: zero is a valid initialization for ifreq.
        let mut request: libc::ifreq = unsafe { zeroed() };
        for (target, source) in request
            .ifr_name
            .iter_mut()
            .zip(interface.as_bytes_with_nul())
        {
            *target = *source as libc::c_char;
        }
        // SAFETY: request contains a NUL-terminated interface name and points to
        // writable storage for the ioctl result.
        let result = unsafe {
            libc::ioctl(
                descriptor.as_raw_fd(),
                libc::SIOCGIFHWADDR,
                &raw mut request,
            )
        };
        let error = io::Error::last_os_error();
        if result < 0 {
            return Err(TransportError(format!(
                "cannot read source MAC for {interface:?}: {error}"
            )));
        }
        // SAFETY: SIOCGIFHWADDR initialized the sockaddr member of this union.
        let data = unsafe { request.ifr_ifru.ifru_hwaddr.sa_data };
        Ok(data[..6]
            .iter()
            .map(|byte| *byte as u8)
            .collect::<Vec<_>>()
            .try_into()
            .expect("six MAC bytes"))
    }

    fn random_marker() -> Result<[u8; 8], TransportError> {
        let mut marker = [0_u8; 8];
        let mut filled = 0;
        while filled < marker.len() {
            // SAFETY: the remaining marker slice is valid and writable.
            let count = unsafe {
                libc::getrandom(
                    marker[filled..].as_mut_ptr().cast(),
                    marker.len() - filled,
                    0,
                )
            };
            if count < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(TransportError(format!(
                    "cannot generate loopback marker: {error}"
                )));
            }
            if count == 0 {
                return Err(TransportError(
                    "kernel returned no loopback-marker entropy".to_owned(),
                ));
            }
            filled += count as usize;
        }
        Ok(marker)
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn ethernet_frame_matches_pinned_oasm_padding_layout() {
            let packet = WirePacket {
                destination_mac: [2; 6],
                source_mac: [1; 6],
                ether_type: ETHER_TYPE,
                loopback_marker: [9; 8],
                payload: vec![0xaa, 0xbb],
            };

            let bytes = RawEthernetTransport::ethernet_bytes(&packet);

            assert_eq!(&bytes[..6], &[2; 6]);
            assert_eq!(&bytes[6..12], &[1; 6]);
            assert_eq!(&bytes[12..14], &ETHER_TYPE.to_be_bytes());
            assert_eq!(&bytes[14..22], &[9; 8]);
            assert_eq!(&bytes[22..46], &[0; 24]);
            assert_eq!(&bytes[46..], &[0xaa, 0xbb]);
        }
    }
}

#[cfg(target_os = "linux")]
pub(crate) use linux::RawEthernetTransport;

#[cfg(not(target_os = "linux"))]
#[derive(Debug)]
pub(crate) struct RawEthernetTransport {
    config: RawSocketConfig,
}

#[cfg(not(target_os = "linux"))]
impl RawEthernetTransport {
    pub(crate) const fn new(config: RawSocketConfig) -> Self {
        Self { config }
    }
}

#[cfg(not(target_os = "linux"))]
impl Transport for RawEthernetTransport {
    fn open(&mut self) -> Result<TransportEnvelope, TransportError> {
        Err(TransportError(format!(
            "Linux AF_PACKET runtime is unsupported on this platform \
             (interface {:?}, destination MAC {:?})",
            self.config.interface, self.config.destination_mac
        )))
    }

    fn send(&mut self, _packet: &WirePacket) -> Result<(), super::SendError> {
        Err(super::SendError {
            rejection: super::SendRejection::AcceptanceUnknown,
            message: "unsupported transport cannot send".to_owned(),
        })
    }

    fn receive(
        &mut self,
        _deadline: std::time::Instant,
    ) -> Result<Option<WirePacket>, super::ReceiveError> {
        Err(super::ReceiveError(
            "unsupported transport cannot receive".to_owned(),
        ))
    }

    fn close(&mut self) {}
}
