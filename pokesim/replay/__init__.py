"""Replay a ladder rung at any commit and find where two commits start to play differently.

``python -m pokesim.replay`` records one rung with a trace, compares two recorded runs and bisects the merged
pull requests between a good and a bad commit. ``rung`` holds the runner the ladder gate and the replay audit
share. Nothing here runs inside the application.
"""
