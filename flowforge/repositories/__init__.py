"""Persistence functions.

Repository functions only ``flush``; they never commit. The caller owns the transaction
(``async with session.begin(): ...``), so several calls can be combined atomically.
"""
