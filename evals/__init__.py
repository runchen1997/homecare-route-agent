"""Evaluating the planner: a fixed set of cases, each with an answer key, scored the same way every run.

cases.py holds the cases: a patient list, the nurse's home as written, how the nurse travels and the
rules. keys.py works out each case's answer key: the best plan by the nurse's preference, by
trying every plan with each patient's true window, not the model's reading of it.
"""
