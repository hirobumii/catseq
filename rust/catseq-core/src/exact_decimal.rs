//! Checked decimal arithmetic used before a value becomes an integer cycle count.

use std::cmp::Ordering;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExactDecimal {
    numerator: i128,
    denominator: i128,
}

impl ExactDecimal {
    pub const fn from_i64(value: i64) -> Self {
        Self {
            numerator: value as i128,
            denominator: 1,
        }
    }

    pub const fn from_u64(value: u64) -> Self {
        Self {
            numerator: value as i128,
            denominator: 1,
        }
    }

    pub fn from_f64_shortest(value: f64) -> Option<Self> {
        value
            .is_finite()
            .then(|| value.to_string())
            .and_then(|value| Self::parse(&value))
    }

    pub fn parse(value: &str) -> Option<Self> {
        let (mantissa, exponent) = if let Some((mantissa, exponent)) = value.split_once(['e', 'E'])
        {
            (mantissa, exponent.parse::<i32>().ok()?)
        } else {
            (value, 0)
        };
        let negative = mantissa.starts_with('-');
        let mantissa = mantissa.trim_start_matches(['-', '+']);
        let (whole, fraction) = mantissa.split_once('.').unwrap_or((mantissa, ""));
        if whole.is_empty() && fraction.is_empty() {
            return None;
        }
        let digits = format!("{whole}{fraction}");
        let mut numerator = digits.parse::<i128>().ok()?;
        if negative {
            numerator = numerator.checked_neg()?;
        }
        let scale = i32::try_from(fraction.len()).ok()?.checked_sub(exponent)?;
        if scale >= 0 {
            let denominator = 10_i128.checked_pow(scale as u32)?;
            Self::new(numerator, denominator)
        } else {
            let multiplier = 10_i128.checked_pow(scale.unsigned_abs())?;
            Self::new(numerator.checked_mul(multiplier)?, 1)
        }
    }

    pub fn checked_add(self, other: Self) -> Option<Self> {
        Self::new(
            self.numerator
                .checked_mul(other.denominator)?
                .checked_add(other.numerator.checked_mul(self.denominator)?)?,
            self.denominator.checked_mul(other.denominator)?,
        )
    }

    pub fn checked_sub(self, other: Self) -> Option<Self> {
        self.checked_add(other.checked_neg()?)
    }

    pub fn checked_mul(self, other: Self) -> Option<Self> {
        Self::new(
            self.numerator.checked_mul(other.numerator)?,
            self.denominator.checked_mul(other.denominator)?,
        )
    }

    pub fn checked_div(self, other: Self) -> Option<Self> {
        if other.numerator == 0 {
            return None;
        }
        let sign = if other.numerator < 0 { -1 } else { 1 };
        Self::new(
            self.numerator
                .checked_mul(other.denominator)?
                .checked_mul(sign)?,
            self.denominator
                .checked_mul(other.numerator.checked_abs()?)?,
        )
    }

    pub fn checked_rem(self, other: Self) -> Option<Self> {
        if other.numerator == 0 {
            return None;
        }
        Self::from_f64_shortest(self.to_f64().rem_euclid(other.to_f64()))
    }

    pub fn checked_neg(self) -> Option<Self> {
        Self::new(self.numerator.checked_neg()?, self.denominator)
    }

    pub fn maximum(self, other: Self) -> Option<Self> {
        let left = self.numerator.checked_mul(other.denominator)?;
        let right = other.numerator.checked_mul(self.denominator)?;
        Some(if left.cmp(&right) == Ordering::Less {
            other
        } else {
            self
        })
    }

    pub fn checked_cmp(self, other: Self) -> Option<Ordering> {
        let left = self.numerator.checked_mul(other.denominator)?;
        let right = other.numerator.checked_mul(self.denominator)?;
        Some(left.cmp(&right))
    }

    pub fn to_cycle_count(self) -> Option<u64> {
        if self.numerator < 0 || self.numerator % self.denominator != 0 {
            return None;
        }
        u64::try_from(self.numerator / self.denominator).ok()
    }

    pub fn to_cycle_count_rounded(self) -> Option<u64> {
        if self.numerator < 0 {
            return None;
        }
        let quotient = self.numerator / self.denominator;
        let remainder = self.numerator % self.denominator;
        let twice_remainder = remainder.checked_mul(2)?;
        let rounded = if twice_remainder > self.denominator
            || (twice_remainder == self.denominator && quotient % 2 != 0)
        {
            quotient.checked_add(1)?
        } else {
            quotient
        };
        u64::try_from(rounded).ok()
    }

    pub fn to_f64(self) -> f64 {
        self.numerator as f64 / self.denominator as f64
    }

    fn new(numerator: i128, denominator: i128) -> Option<Self> {
        if denominator <= 0 {
            return None;
        }
        let divisor = gcd(numerator.unsigned_abs(), denominator as u128) as i128;
        Some(Self {
            numerator: numerator / divisor,
            denominator: denominator / divisor,
        })
    }
}

fn gcd(mut left: u128, mut right: u128) -> u128 {
    while right != 0 {
        (left, right) = (right, left % right);
    }
    left.max(1)
}

#[cfg(test)]
mod tests {
    use super::ExactDecimal;

    #[test]
    fn decimal_duration_math_is_exact() {
        let scan = ExactDecimal::parse("0.02").unwrap();
        let cycles_per_us = ExactDecimal::from_u64(250);

        assert_eq!(
            scan.checked_mul(cycles_per_us).unwrap().to_cycle_count(),
            Some(5)
        );
        assert_eq!(
            ExactDecimal::parse("0.021")
                .unwrap()
                .checked_mul(cycles_per_us)
                .unwrap()
                .to_cycle_count(),
            None
        );
    }
}
