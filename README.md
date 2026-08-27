# PostgreSQLMultiGraphMatch

A smaller-scale reference port of [`MultiQuery`](../MultiQuery)'s
subgraph-matching pipeline — Cypher parsing, bit-signature
compatibility-domain pruning, and the multi-way join — written in Python
against a plain PostgreSQL database. No Spark, no Iceberg, no distributed
execution: everything runs in-process. It exists as a simpler, more easily
inspected mirror of `MultiQuery`, not a separate line of research — every
major Scala module has a named Python counterpart.
