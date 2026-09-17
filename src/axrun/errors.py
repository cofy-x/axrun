"""Stable Axrun errors."""


class AxrunError(RuntimeError):
    """Base error for runner-owned failures."""


class ContractError(AxrunError, ValueError):
    """A caller-owned episode or adapter contract is invalid."""


class InfrastructureError(AxrunError):
    """The execution platform could not produce a trustworthy outcome."""


class RecoveryRequiredError(AxrunError):
    """A persisted stage must be inspected instead of silently rerun."""


class SdkCapabilityError(AxrunError):
    """The installed public Axern SDK lacks a required stable capability."""
