"""Job orchestration package.

Each module here is a CLI entrypoint for one of the app's daily jobs
(ingestion, trigger checking). These are the only modules that wire
adapters, domain logic, and data access together into a full workflow.
"""
