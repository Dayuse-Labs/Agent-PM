"""Sparse JSON format for the single triage call.

The complete all-fields schema regressed semantic behavior in the v73 replay.
Use the verified v72 request contract; validators still own accepted updates.
"""

TRIAGE_RESPONSE_FORMAT = {"type": "json_object"}
