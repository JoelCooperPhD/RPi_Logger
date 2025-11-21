"""
Discovery combiner specification.

- Purpose: merge results from USB and Pi camera discovery into a unified list, resolve id collisions, and apply filtering policies (max cameras, preferred backends).
- Responsibilities: dedupe by stable identifiers, annotate source, and emit unified events to registry; handle partial failures gracefully.
- Logging: summary of merged results, conflicts resolved, filtered devices, and errors.
"""
