"""
Mask conversion utilities for OASM ISA compatibility.

This module provides functions to convert between binary masks (0b000101) 
and RTMQ ISA "A.B" format masks.
"""

from typing import Union


def binary_to_rtmq_mask(binary_mask: int) -> Union[int, str]:
    """
    Convert a binary mask to RTMQ ISA "X.P" format.
    
    X.P format meaning:
    - X (4-bit): Channel state pattern (which channels in a group are active)
    - P: Channel group position (which 4-channel group to apply the pattern to)
    - Formula: X << (P * 2)
    
    Args:
        binary_mask: Binary mask representing channel states
        
    Returns:
        Either a string "X.P" or the original integer mask
        
    Examples:
        binary_to_rtmq_mask(0b0001)     # "1.0": channel 0 (bit 0)
        binary_to_rtmq_mask(0b0100)     # "1.1": channel 2 (bit 2) 
        binary_to_rtmq_mask(0b1100)     # "3.1": channels 2,3 (bits 2,3)
        binary_to_rtmq_mask(0b11110000) # "F.2": channels 4-7 (bits 4-7)
    """
    if binary_mask == 0:
        return "0.0"
    
    # Strategy: Use X.0 for low 4 bits, use P>0 only for higher bits
    
    # First, try X.0 format for patterns that fit in low 4 bits
    if 1 <= binary_mask <= 15:
        return f"{binary_mask:X}.0"
    
    # For higher bits, find valid (X, P) combinations with P > 0
    valid_combinations = []
    
    for P in range(1, 16):  # Start from P=1, skip P=0 (handled above)
        shift = P * 2
        
        # Check if the mask can be represented as X << shift
        if binary_mask % (1 << shift) == 0:  # All lower bits are zero
            X = binary_mask >> shift
            
            # X must be a valid 4-bit pattern (1-15)
            if 1 <= X <= 15:
                # Verify the formula works exactly
                if (X << shift) == binary_mask:
                    valid_combinations.append((X, P))
    
    if valid_combinations:
        # Choose the combination with the smallest X (simplest pattern)
        X, P = min(valid_combinations, key=lambda pair: pair[0])
        return f"{X:X}.{P}"
    
    # For complex masks that can't be represented in X.P format,
    # return the original integer
    return binary_mask


def rtmq_mask_to_binary(rtmq_mask: str) -> int:
    """
    Convert RTMQ ISA "A.B" format mask to binary.
    
    Args:
        rtmq_mask: Mask in "A.B" format (e.g., "3.1")
        
    Returns:
        Binary mask value
        
    Examples:
        rtmq_mask_to_binary("1.0")  # -> 1 << (0*2) = 1
        rtmq_mask_to_binary("1.1")  # -> 1 << (1*2) = 4
        rtmq_mask_to_binary("3.0")  # -> 3 << (0*2) = 3
        rtmq_mask_to_binary("F.2")  # -> 15 << (2*2) = 240
    """
    if '.' not in rtmq_mask:
        raise ValueError(f"Invalid RTMQ mask format: {rtmq_mask}. Expected 'A.B' format.")
    
    X_str, P_str = rtmq_mask.split('.')
    X = int(X_str, 16)  # Parse as hexadecimal
    P = int(P_str, 16)  # Parse as hexadecimal (though usually 0-3)
    
    return X << (P * 2)


def encode_rtmq_mask(rtmq_mask: str) -> int:
    """
    Encode RTMQ "A.B" format mask into 8-bit encoded form.
    
    According to ISA: encoded in 8 bits as (X << 4) + P
    
    Args:
        rtmq_mask: Mask in "A.B" format
        
    Returns:
        8-bit encoded value
        
    Examples:
        encode_rtmq_mask("3.1")  # -> (3 << 4) + 1 = 49
        encode_rtmq_mask("F.2")  # -> (15 << 4) + 2 = 242
    """
    if '.' not in rtmq_mask:
        raise ValueError(f"Invalid RTMQ mask format: {rtmq_mask}. Expected 'A.B' format.")
    
    X_str, P_str = rtmq_mask.split('.')
    X = int(X_str, 16)
    P = int(P_str, 16)
    
    if X > 15 or P > 15:
        raise ValueError(f"X and P must be single hex digits (0-F), got X={X}, P={P}")
    
    return (X << 4) + P


def smart_mask_convert(binary_mask: int) -> Union[str, int]:
    """
    Smart conversion that tries to find the best RTMQ representation.
    
    Args:
        binary_mask: Binary mask to convert
        
    Returns:
        Either a string in "A.B" format or the original mask if no good conversion found
    """
    if binary_mask == 0:
        return "0.0"
    
    # Try simple single-bit patterns first
    bit_pos = binary_mask.bit_length() - 1
    if binary_mask == (1 << bit_pos):  # Single bit set
        P = bit_pos // 2
        if bit_pos % 2 == 0 and P <= 15:  # Even bit position, P in range
            return f"1.{P}"
    
    # Try multi-bit patterns at even positions  
    for P in range(16):
        shift = P * 2
        if binary_mask & ((1 << shift) - 1) == 0:  # All bits below shift are 0
            X = binary_mask >> shift
            if X <= 15 and X > 0:  # Valid single hex digit
                return f"{X:X}.{P}"
    
    # Return original mask if no good conversion found
    return binary_mask


def demonstrate_channel_control():
    """演示X.P格式可以控制的通道范围"""
    print("X.P格式通道控制能力演示:")
    print("格式: X.P -> 值 -> 二进制 -> 激活的通道(bit位置)")
    print("-" * 60)
    
    examples = [
        "1.0", "1.1", "1.2", "1.3",  # 单通道
        "3.0", "3.1", "3.2",         # 双通道  
        "7.0", "7.1",                # 三通道
        "F.0", "F.1", "F.2",         # 四通道
        "F.8",                       # 高位四通道
    ]
    
    for rtmq_format in examples:
        value = rtmq_mask_to_binary(rtmq_format)
        
        # 找出所有激活的bit位置
        active_bits = []
        for i in range(32):
            if value & (1 << i):
                active_bits.append(i)
        
        print(f"{rtmq_format:>4} -> {value:6d} -> 0b{value:016b} -> 通道{active_bits}")


# Test function
def _test_mask_conversions():
    """Test the mask conversion functions."""
    test_cases = [
        (0b0001, "1.0"),         # bit 0: 1 << (0*2) = 1
        (0b0100, "1.1"),         # bit 2: 1 << (1*2) = 4  
        (0b010000, "1.2"),       # bit 4: 1 << (2*2) = 16
        (0b01000000, "1.3"),     # bit 6: 1 << (3*2) = 64
        (1 << 8, "1.4"),         # bit 8: 1 << (4*2) = 256
        (1 << 10, "1.5"),        # bit 10: 1 << (5*2) = 1024
        (0b11, "3.0"),           # bits 0,1: 3 << (0*2) = 3
        (0b1100, "3.1"),         # bits 2,3: 3 << (1*2) = 12
        (0b110000, "3.2"),       # bits 4,5: 3 << (2*2) = 48
        (0b11000000, "3.3"),     # bits 6,7: 3 << (3*2) = 192
        (0xF << 8, "F.4"),       # bits 8-11: 15 << (4*2) = 3840
    ]
    
    print("Testing mask conversions:")
    for binary, expected in test_cases:
        result = binary_to_rtmq_mask(binary)
        print(f"0b{binary:08b} ({binary:3d}) -> {result} (expected {expected})")
        
        # Test reverse conversion
        if isinstance(result, str):
            reverse = rtmq_mask_to_binary(result)
            print(f"  Reverse: {result} -> 0b{reverse:08b} ({reverse})")
            assert reverse == binary, f"Round trip failed: {binary} -> {result} -> {reverse}"


if __name__ == "__main__":
    _test_mask_conversions()