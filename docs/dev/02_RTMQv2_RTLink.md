# RTMQv2 Reference \#2 - RTLink Network

by Zhang Junhua

Rev.0.1 - 2024.05.13

## Introduction

A single chip can do just so much about control. If you have a huge system, you'll need many chips, or even subsystems, in cooperation to make it work. In RTMQ framework, a dedicated networking protocol, **RTLink**, is designed to guarantee synchronization and precise timing between different parts of the system.

In an RTLink network, an entity with independent function and processing capability is termed a *node*. There are 2 types of nodes in the network:

- **Coherent Node**: Nodes designed in RTMQ framework, whose timing is inherently deterministic and precise. And timing control is a part of their functionality.
- **Non-coherent Node**: Nodes not in RTMQ framework, but are compatible to RTLink protocol. They can be devices doing non-realtime control or monitoring, or computers providing user access and general computing power.

As in OSI's 7-layer model, RTLink is a protocol in the Data Link Layer and the Network Layer. It is independent of physical media of connections between nodes. The only 2 requirements to the media is that:

- The connection shall be point to point.
- The latency shall be deterministic.

Seen from the top level, an RTLink network is a *decentralized* and *static* network, that is:

- **Decentralized**: There is no master node or root node in the network. All nodes can equally share data with or request cooperation from other nodes. Although in practice it is OK to manually define a root node for convenience.
- **Static**: When new nodes are online or existing nodes are offline, the topology of the network shall be explored again and routing data in every node shall be updated.

## Abstraction of a Node

### Channels in a Node

- Each node can physically connect to at most 32 other nodes. These nodes are *neighbors* of the current node. The corresponding connections are *remote channels* of the current node.
- Each remote channel of a node can be independently configured for propagating broadcast frames or not.
- Each module in a node that can generate or consume RTLink frames corresponds to a *local channel* of the node. There can be at most 32 local channels for a node.
- For coherent nodes, local channel #0 corresponds to the RT-Core (the realtime processor in RTMQ framework).
- For non-coherent nodes, local channel #0 shall correspond to the main controller of the node.

### Identification of a Node

- Each node in an RTLink network shall have an address that is unique in the network for routing purpose.
- The address is 16-bit wide and shall be dynamically assignable. However, address `0xFFFF` is reserved as wildcard address of current node.
- The 4 MSB of the address is the cluster address, and the 12 LSB is the subnet address.
- Each node may have a GUID (globally unique identifier) as auxiliary information to identify itself. It can be hardcoded in the node.

### Routing Behavior of a Node

- Each node shall locally maintain 2 routing tables, 1 for inter-cluster routing, 1 for subnet routing.
- If the current node is the destination of an RTLink frame, the frame shall be delivered to the designated local channel to be consumed.
- If not, the routing tables are used to determine to which remote channel shall this frame be forwarded. If the destination is not in the same cluster as current node, the inter-cluster routing table is used, otherwise the subnet routing table is used.

## Structure of an RTLink Frame

Data transferred through RTLink network is in unit of frames. An RTLink frame to be processed by a node has a fixed length of 108 bits. However, depending on physical layer implementation, frames actually transferred in remote channels may have extra header and/or trailing fields. The structure of a frame is as follows.

|     | Field | Width (bits) | Meaning |
|:---:|:-----:|:------------:|:--------|
| MSB |  TYP  |      1       | Frame type: 0 for data (non-realtime) frame, 1 for instruction (realtime) frame |
|     |  SRF  |      2       | Special routing flag: see **Routing Protocol** section for details |
|     |  CHN  |      5       | Destination local channel |
|     |  ADR  |     16       | Destination node address |
|     |  TAG  |     20       | Tag for data frame / Latency (signed) for instruction frame |
| LSB |  PLD  |     64       | Payload of the frame |

## Routing Protocol

Depending on the TYP field, a frame can either be a data frame (`TYP == 0`) or an instruction frame (`TYP == 1`). Instruction frames are realtime, while data frames are non-realtime and have lower routing priority than instruction frames. The TAG field of a data frame is the tag of the payload. When the frame is relayed, the TAG field shall be forwarded as-is. While the TAG field of an instruction frame is the required latency of the payload, characterizing the required duration between the generation and the consumption of the frame, in unit of clock cycles. When an instruction frame is relayed, the processing overhead in current node and the communication latency in the forwarding remote channel shall be reduced from the TAG field.

Depending on the SRF field, a frame can be one of the 4 types:

- `SRF == 00`: normal frame
- `SRF == 01`: broadcast frame
- `SRF == 10`: echo frame
- `SRF == 11`: directed frame

The routing protocol for each type will be explained in detail in the following subsections.

### Normal Frame

Normal frames are *normal*. They are used for ordinary point-to-point communication between 2 nodes in the network.

When a normal frame is submitted to the routing logic for processing (whether it is received from a remote channel or generated from a local channel):

- If the ADR field matches the address of current node or equals `0xFFFF` (wildcard address), the frame shall be delivered to the destination local channel determined by CHN field.
- Otherwise, read the local routing table with the ADR field as the index:
  - If valid entry is found, forward the frame to the remote channel according to the found entry.
  - If not, discard the frame.

### Broadcast Frame

Broadcast frames are used for broadcasting instructions or sharing data in a sector of the network.

When a broadcast frame is submitted to the routing logic for processing (whether it is received from a remote channel or generated from a local channel):

- If the ADR field matches the address of current node or equals `0xFFFF` (wildcard address):
  - Deliver the frame to the destination local channel determined by CHN field.
  - Also forward the frame with its ADR field changed to `0xFFFF`, to every remote channel with broadcast propagation enabled.
- Otherwise, read the local routing table with the ADR field as the index:
  - If valid entry is found, forward the frame to the remote channel according to the found entry.
  - If not, discard the frame.

### Echo Frame

Echo frames are used when the network is newly assembled, and its topology remains to be explored. With echo frames, a node can probe the existence and type of its neighbors, and calibrate the communication latency of its remote channels.

- When an echo frame is generated from a local channel, forward it to the remote channel determined by the 5 LSBs of the ADR field.
- When an echo frame is received from a remote channel, reply a directed frame to that remote channel, with:
  - TYP, CHN and TAG field same as that echo frame,
  - PLD field same as that echo frame, if it is an instruction frame,
  - PLD field containing the incoming remote channel number with respect to the receiving node, the address and optionally GUID of the receiving node, if the echo frame is a data frame.

### Directed Frame

Directed frames are used when the exploration of the network is not yet finished, such that a valid routing table is not available. They can be sent though designated remote channels without the information of addresses.

- When a directed frame is generated from a local channel, forward it to the remote channel determined by the 5 LSBs of the ADR field.
- When a directed frame is received from a remote channel, deliver it to the destination local channel determined by the CHN field.

## Consumption of Frames

### Data Frame

A data frame contains 64 bits of data as its payload. When local channel #0 of a node receives a data frame, its payload shall be saved to memory with its TAG field as the index, such that the main controller of the node (for a coherent node, its RT-Core) can access later. The consumption behavior of other local channels can be arbitrarily defined by the designer of the node.

### Instruction Frame

An instruction frame contains the machine codes of 2 instructions in RTMQ ISA as its payload. When local channel #0 of a coherent node receives an instruction frame:

- The frame shall first be buffered in a pool, until the remaining latency determined by its TAG field elapsed.
  - But if the remaining latency is negative, proceed to the next step immediately.
- Then the 2 instructions shall be submitted to the RT-Core of the node for execution, first the instruction in 32 MSBs of the PLD field, then the instruction in 32 LSBs.
- The RT-Core shall execute the 2 instructions one by one immediately, regardless of its hold/halt state, also suspending instruction fetch from the cache.

The consumption behavior of other local channels, and that of non-coherent nodes, can be arbitrarily defined by the designer.

## Establishing an RTLink Network

When an RTLink network is freshly assembled, the routing table in each node is yet to be configured. Although you can manually configure all of them one by one, but for a network with hundreds of nodes, obviously you won't get the job done today. Instead, you can:

- First explore the network with breadth-first search to figure out its topology.
- Then compute shortest paths between each pair of nodes.
- And finally generate all the routing tables with optimal routing scheme automatically.

Here are the detailed steps.

- Start with any node, put it into a queue of nodes that are going to be explored.
- With the first node in the queue:
  - Send echo data frames with different TAG field through each of its remote channels.
  - Wait for some time, then check the memory with each TAG field to see if any neighbor replied and what are they.
  - For each of those who replied:
    - If the neighbor does not reply with a valid address:
      - Assign one to it with directed instruction frames.
      - Then append the neighbor to the end of the queue.
    - Send an echo instruction frame to measure the round-trip latency through the corresponding remote channel.
  - Remove the node from the queue.
- Repeat last step until the queue is empty.
- Now you have the topology of the network and communication latency of all the connections.
- Compute the shortest paths between each pair of nodes with the Floyd algorithm.
- Construct the routing table of each node according to the shortest paths.
