You are checking for semantic duplicates in a personal belief system.

CANDIDATE BELIEF:
"{candidate}"

EXISTING BELIEFS:
{beliefs_list}

TASK:
Determine if the candidate belief is:
1. UNIQUE - Genuinely new, not semantically equivalent to any existing belief
2. DUPLICATE - Semantically equivalent to an existing belief (same core claim, just different wording)
3. RELATED - Different claim but closely related (would benefit from linking)

IMPORTANT:
- DUPLICATE means the same claim restated. "AI will change coding" and "Machine learning will transform software development" are DUPLICATES.
- RELATED means different but connected claims. "AI will change coding" and "AI reduces development costs" are RELATED.
- When in doubt between DUPLICATE and RELATED, prefer RELATED.

Respond with EXACTLY one line in this format:
UNIQUE|No existing belief makes this claim
DUPLICATE|<slug>|<brief reason>
RELATED|<slug>|<brief reason>

Just the one line, nothing else.
