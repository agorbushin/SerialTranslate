# Translation Wrapper Function Plan

## Problem

- `send_rare_hard_words()` needs to translate tier_2 when button is clicked
- Currently calls `translate_tier_list()` which translates both tier_1 and tier_2
- User wants tier_2 to use the same translation process as tier_1
- Need a unified wrapper function for translation check and trigger

## Solution

Create a unified wrapper function that:
1. Checks if translation is needed (same logic for any tier file)
2. Triggers translation for a specific tier file
3. Uses the same process as tier_1 (same checks, same filters)

## Implementation Plan

### Step 1: Create Unified Translation Check Function

```python
async def check_and_translate_tier_file(
    update: Update,
    tier_file: Path,
    episode_dir: Path,
    tier_name: str = "tier file"
) -> tuple[bool, bool]:
    """
    Unified function to check translation status and trigger translation if needed.
    
    Returns:
        (needs_translation: bool, translate_success: bool)
    """
    # Check if translation is needed (same logic for all tiers)
    # Trigger translation if needed
    # Return status
```

### Step 2: Modify send_rare_hard_words()

- Use the wrapper function instead of calling `translate_tier_list()`
- Translate tier_2 directly using `translate_tier_file()`
- Same process as tier_1

### Step 3: Refactor send_tier_list_results()

- Use the same wrapper function for consistency
- Keep existing behavior but use unified code

## Benefits

- Consistent translation logic across all tiers
- Same checks and filters for tier_1 and tier_2
- Easier to maintain (single source of truth)
- Can be reused for tier_4 and other tiers
