"""Normalized taxonomy and label-quality audit (Milestone 4).

Original labels are immutable: a normalized label is added next to each one through
``configs/taxonomy.yaml``, every mapping carries a status and its evidence, and nothing is
relabelled. The code knows source ids and labels only through the configuration.
"""
