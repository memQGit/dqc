# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Canonical JSON configuration support for quantum networks.

This module provides a stable, translation-oriented JSON representation for
quantum networks. The canonical format is broader than the legacy network
graph JSON used by :class:`memq_dqc.network.NetworkGraph`: it captures
topology, local hardware, reusable noise models, protocols, observables, and
simulation settings with explicit cross-references by string ID.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

JsonPrimitive = str | int | float | bool | None
JsonValue = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

DEFAULT_CANONICAL_NETWORK_UNITS: JsonObject = {
    "time": "ns",
    "frequency": "Hz",
    "distance": "m",
    "probability": "unitless",
}

_LIST_SECTIONS = (
    "nodes",
    "channels",
    "links",
    "memories",
    "processors",
    "noise_models",
    "protocols",
    "constraints",
    "observables",
)

_DEFAULT_TOP_LEVEL_VALUES: dict[str, JsonValue] = {
    "nodes": [],
    "channels": [],
    "links": [],
    "memories": [],
    "processors": [],
    "noise_models": [],
    "protocols": [],
    "constraints": [],
    "initial_state": {},
    "observables": [],
    "simulation": {},
    "mapping_hints": {},
}

_REFERENCE_FIELDS: dict[str, str] = {
    "channel_id": "channels",
    "channel_ids": "channels",
    "link_id": "links",
    "link_ids": "links",
    "memory_id": "memories",
    "memory_ids": "memories",
    "node_id": "nodes",
    "node_ids": "nodes",
    "noise_model_id": "noise_models",
    "noise_model_ids": "noise_models",
    "processor_id": "processors",
    "processor_ids": "processors",
    "source": "nodes",
    "target": "nodes",
}

_TOP_LEVEL_KEY_ORDER = (
    "version",
    "units",
    "metadata",
    "nodes",
    "channels",
    "links",
    "memories",
    "processors",
    "noise_models",
    "protocols",
    "constraints",
    "initial_state",
    "observables",
    "simulation",
    "mapping_hints",
)

_OBJECT_KEY_ORDER = (
    "id",
    "type",
    "label",
    "role",
    "channel_type",
    "source",
    "target",
    "bidirectional",
    "node_id",
    "node_ids",
    "memory_id",
    "memory_ids",
    "processor_id",
    "processor_ids",
    "channel_id",
    "channel_ids",
    "participants",
    "position",
    "ports",
    "trigger",
    "requirements",
    "success_conditions",
    "failure_policy",
    "delay_model",
    "loss_model",
    "noise_model_id",
    "noise_model_ids",
    "parameters",
    "custom",
)


class CanonicalNetworkConfigError(ValueError):
    """Raised when a canonical network configuration is invalid."""


def build_canonical_network_config(
    definition: dict[str, Any],
) -> JsonObject:
    """Normalize and validate a canonical network configuration.

    Args:
        definition: In-memory network definition to normalize into the
            canonical JSON structure.

    Returns:
        A validated configuration dictionary with deterministic section
        ordering and defaulted top-level sections.

    Raises:
        CanonicalNetworkConfigError: If the definition has invalid structure,
            unsupported JSON values, or broken cross-references.
    """
    if not isinstance(definition, dict):
        raise CanonicalNetworkConfigError(
            "Canonical network definitions must be dictionaries."
        )

    version = definition.get("version", "1.0")
    if not isinstance(version, str) or not version:
        raise CanonicalNetworkConfigError(
            "The top-level 'version' field must be a non-empty string."
        )

    units = _normalize_top_level_mapping(
        "units",
        definition.get("units", DEFAULT_CANONICAL_NETWORK_UNITS),
    )
    normalized_units = dict(DEFAULT_CANONICAL_NETWORK_UNITS)
    normalized_units.update(units)

    metadata = _normalize_top_level_mapping(
        "metadata",
        definition.get("metadata", {}),
    )
    initial_state = _normalize_top_level_mapping(
        "initial_state",
        definition.get("initial_state", {}),
    )
    simulation = _normalize_top_level_mapping(
        "simulation",
        definition.get("simulation", {}),
    )
    mapping_hints = _normalize_top_level_mapping(
        "mapping_hints",
        definition.get("mapping_hints", {}),
    )

    config: JsonObject = {
        "version": version,
        "units": normalized_units,
        "metadata": metadata,
        "initial_state": initial_state,
        "simulation": simulation,
        "mapping_hints": mapping_hints,
    }

    for section in _LIST_SECTIONS:
        config[section] = cast(
            JsonValue,
            _normalize_object_list(
                section,
                definition.get(section, _DEFAULT_TOP_LEVEL_VALUES[section]),
            ),
        )

    validate_canonical_network_config(config)
    return _sorted_config(config)


def validate_canonical_network_config(config: dict[str, Any]) -> None:
    """Validate a canonical network configuration in-place.

    Args:
        config: Canonical network configuration to validate.

    Raises:
        CanonicalNetworkConfigError: If the configuration is invalid.
    """
    _ensure_json_compatible(config, "config")

    ids_by_section: dict[str, set[str]] = {}
    all_ids: set[str] = set()
    for section in _LIST_SECTIONS:
        section_value = config.get(section, [])
        if not isinstance(section_value, list):
            raise CanonicalNetworkConfigError(
                f"The top-level '{section}' section must be a list."
            )
        section_ids: set[str] = set()
        for obj in section_value:
            if not isinstance(obj, dict):
                raise CanonicalNetworkConfigError(
                    f"Entries in '{section}' must be objects."
                )
            object_id = obj["id"]
            if object_id in section_ids:
                raise CanonicalNetworkConfigError(
                    f"Duplicate ID {object_id!r} found in section '{section}'."
                )
            if object_id in all_ids:
                raise CanonicalNetworkConfigError(
                    f"Duplicate ID {object_id!r} found across canonical "
                    "network sections."
                )
            section_ids.add(object_id)
            all_ids.add(object_id)
        ids_by_section[section] = section_ids

    for obj in cast(list[JsonObject], config["nodes"]):
        _validate_reference_list(
            obj,
            field_name="memory_ids",
            target_ids=ids_by_section["memories"],
        )
        _validate_reference_list(
            obj,
            field_name="processor_ids",
            target_ids=ids_by_section["processors"],
        )
        _validate_ports(obj)

    for obj in cast(list[JsonObject], config["channels"]):
        _validate_reference_scalar(
            obj,
            field_name="source",
            target_ids=ids_by_section["nodes"],
        )
        _validate_reference_scalar(
            obj,
            field_name="target",
            target_ids=ids_by_section["nodes"],
        )
        _validate_optional_bool(obj, "bidirectional")

    for obj in cast(list[JsonObject], config["links"]):
        _validate_reference_list(
            obj,
            field_name="channel_ids",
            target_ids=ids_by_section["channels"],
        )
        _validate_reference_list(
            obj,
            field_name="node_ids",
            target_ids=ids_by_section["nodes"],
        )

    for section, field_name in (
        ("memories", "node_id"),
        ("processors", "node_id"),
    ):
        for obj in cast(list[JsonObject], config[section]):
            _validate_reference_scalar(
                obj,
                field_name=field_name,
                target_ids=ids_by_section["nodes"],
            )

    for section in ("memories", "channels", "processors"):
        for obj in cast(list[JsonObject], config[section]):
            _validate_reference_scalar(
                obj,
                field_name="noise_model_id",
                target_ids=ids_by_section["noise_models"],
            )
            _validate_reference_list(
                obj,
                field_name="noise_model_ids",
                target_ids=ids_by_section["noise_models"],
            )

    for obj in cast(list[JsonObject], config["protocols"]):
        _validate_reference_list(
            obj,
            field_name="participants",
            target_ids=all_ids,
        )

    for section in ("units", "metadata", "initial_state", "simulation"):
        if not isinstance(config.get(section, {}), dict):
            raise CanonicalNetworkConfigError(
                f"The top-level '{section}' field must be an object."
            )

    if not isinstance(config.get("mapping_hints", {}), dict):
        raise CanonicalNetworkConfigError(
            "The top-level 'mapping_hints' field must be an object."
        )


def dumps_canonical_network_config(
    definition: dict[str, Any],
    *,
    indent: int = 2,
) -> str:
    """Return deterministic JSON for a canonical network configuration.

    Args:
        definition: In-memory network definition or already normalized config.
        indent: Number of spaces used for indentation.

    Returns:
        Deterministic JSON with sorted keys.
    """
    config = build_canonical_network_config(definition)
    ordered_config = _ordered_top_level_config(config)
    return json.dumps(ordered_config, indent=indent)


def write_canonical_network_config(
    definition: dict[str, Any],
    output_path: str | Path,
    *,
    indent: int = 2,
) -> Path:
    """Write a canonical network configuration to disk.

    Args:
        definition: In-memory network definition to serialize.
        output_path: Destination file path.
        indent: Number of spaces used for indentation.

    Returns:
        The resolved path written to disk.
    """
    resolved_path = Path(output_path)
    resolved_path.write_text(
        dumps_canonical_network_config(definition, indent=indent) + "\n",
        encoding="utf-8",
    )
    return resolved_path


@dataclass(slots=True)
class CanonicalNetworkConfigBuilder:
    """Builder for canonical quantum network JSON configurations."""

    version: str = "1.0"
    units: JsonObject = field(
        default_factory=lambda: deepcopy(DEFAULT_CANONICAL_NETWORK_UNITS)
    )
    metadata: JsonObject = field(default_factory=dict)
    initial_state: JsonObject = field(default_factory=dict)
    simulation: JsonObject = field(default_factory=dict)
    mapping_hints: JsonObject = field(default_factory=dict)
    _sections: dict[str, list[JsonObject]] = field(
        default_factory=lambda: {section: [] for section in _LIST_SECTIONS},
        init=False,
        repr=False,
    )

    def add_object(
        self,
        section: str,
        obj: dict[str, Any],
    ) -> CanonicalNetworkConfigBuilder:
        """Add an object to one of the canonical list sections.

        Args:
            section: Canonical top-level list section name.
            obj: Object to add to the section.

        Returns:
            The builder instance for chaining.

        Raises:
            CanonicalNetworkConfigError: If the section name is unsupported.
        """
        if section not in self._sections:
            raise CanonicalNetworkConfigError(
                f"Unsupported canonical section {section!r}."
            )
        self._sections[section].append(_normalize_object(section, obj))
        return self

    def add_node(
        self,
        *,
        id: str,
        type: str,
        label: str | None = None,
        role: str | None = None,
        position: dict[str, Any] | None = None,
        ports: list[dict[str, Any]] | None = None,
        memory_ids: list[str] | None = None,
        processor_ids: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a node definition."""
        node = _object_with_optional_fields(
            id=id,
            type=type,
            label=label,
            role=role,
            position=position,
            ports=ports,
            memory_ids=memory_ids,
            processor_ids=processor_ids,
            parameters=parameters,
            custom=custom,
        )
        return self.add_object("nodes", node)

    def add_channel(
        self,
        *,
        id: str,
        type: str,
        channel_type: str,
        source: str,
        target: str,
        bidirectional: bool | None = None,
        parameters: dict[str, Any] | None = None,
        noise_model_id: str | None = None,
        delay_model: dict[str, Any] | None = None,
        loss_model: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a channel definition."""
        channel = _object_with_optional_fields(
            id=id,
            type=type,
            channel_type=channel_type,
            source=source,
            target=target,
            bidirectional=bidirectional,
            parameters=parameters,
            noise_model_id=noise_model_id,
            delay_model=delay_model,
            loss_model=loss_model,
            custom=custom,
        )
        return self.add_object("channels", channel)

    def add_link(
        self,
        *,
        id: str,
        type: str,
        channel_ids: list[str] | None = None,
        node_ids: list[str] | None = None,
        parameters: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a logical link definition."""
        link = _object_with_optional_fields(
            id=id,
            type=type,
            channel_ids=channel_ids,
            node_ids=node_ids,
            parameters=parameters,
            custom=custom,
        )
        return self.add_object("links", link)

    def add_memory(
        self,
        *,
        id: str,
        type: str,
        node_id: str,
        parameters: dict[str, Any] | None = None,
        noise_model_id: str | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a quantum memory definition."""
        memory = _object_with_optional_fields(
            id=id,
            type=type,
            node_id=node_id,
            parameters=parameters,
            noise_model_id=noise_model_id,
            custom=custom,
        )
        return self.add_object("memories", memory)

    def add_processor(
        self,
        *,
        id: str,
        type: str,
        node_id: str,
        parameters: dict[str, Any] | None = None,
        noise_model_id: str | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a processor definition."""
        processor = _object_with_optional_fields(
            id=id,
            type=type,
            node_id=node_id,
            parameters=parameters,
            noise_model_id=noise_model_id,
            custom=custom,
        )
        return self.add_object("processors", processor)

    def add_noise_model(
        self,
        *,
        id: str,
        type: str,
        parameters: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a reusable noise model definition."""
        noise_model = _object_with_optional_fields(
            id=id,
            type=type,
            parameters=parameters,
            custom=custom,
        )
        return self.add_object("noise_models", noise_model)

    def add_protocol(
        self,
        *,
        id: str,
        type: str,
        participants: list[str] | None = None,
        trigger: JsonValue | None = None,
        requirements: JsonValue | None = None,
        parameters: dict[str, Any] | None = None,
        success_conditions: JsonValue | None = None,
        failure_policy: JsonValue | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a protocol definition."""
        protocol = _object_with_optional_fields(
            id=id,
            type=type,
            participants=participants,
            trigger=trigger,
            requirements=requirements,
            parameters=parameters,
            success_conditions=success_conditions,
            failure_policy=failure_policy,
            custom=custom,
        )
        return self.add_object("protocols", protocol)

    def add_constraint(
        self,
        *,
        id: str,
        type: str,
        parameters: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add a constraint definition."""
        constraint = _object_with_optional_fields(
            id=id,
            type=type,
            parameters=parameters,
            custom=custom,
        )
        return self.add_object("constraints", constraint)

    def add_observable(
        self,
        *,
        id: str,
        type: str,
        parameters: dict[str, Any] | None = None,
        custom: JsonValue | None = None,
    ) -> CanonicalNetworkConfigBuilder:
        """Add an observable definition."""
        observable = _object_with_optional_fields(
            id=id,
            type=type,
            parameters=parameters,
            custom=custom,
        )
        return self.add_object("observables", observable)

    def set_initial_state(
        self,
        initial_state: dict[str, Any],
    ) -> CanonicalNetworkConfigBuilder:
        """Set initial network state assumptions."""
        self.initial_state = _normalize_top_level_mapping(
            "initial_state",
            initial_state,
        )
        return self

    def set_simulation(
        self,
        simulation: dict[str, Any],
    ) -> CanonicalNetworkConfigBuilder:
        """Set simulation settings."""
        self.simulation = _normalize_top_level_mapping(
            "simulation",
            simulation,
        )
        return self

    def set_mapping_hints(
        self,
        mapping_hints: dict[str, Any],
    ) -> CanonicalNetworkConfigBuilder:
        """Set mapping hints for downstream translators."""
        self.mapping_hints = _normalize_top_level_mapping(
            "mapping_hints",
            mapping_hints,
        )
        return self

    def to_definition(self) -> JsonObject:
        """Return the builder state as a plain definition dictionary."""
        definition: JsonObject = {
            "version": self.version,
            "units": deepcopy(self.units),
            "metadata": deepcopy(self.metadata),
            "initial_state": deepcopy(self.initial_state),
            "simulation": deepcopy(self.simulation),
            "mapping_hints": deepcopy(self.mapping_hints),
        }
        for section, objects in self._sections.items():
            definition[section] = cast(JsonValue, deepcopy(objects))
        return definition

    def build(self) -> JsonObject:
        """Build, normalize, and validate the current configuration."""
        return build_canonical_network_config(self.to_definition())

    def dumps(self, *, indent: int = 2) -> str:
        """Serialize the current configuration to deterministic JSON."""
        return dumps_canonical_network_config(
            self.to_definition(), indent=indent
        )

    def write(
        self,
        output_path: str | Path,
        *,
        indent: int = 2,
    ) -> Path:
        """Write the current configuration to disk."""
        return write_canonical_network_config(
            self.to_definition(),
            output_path,
            indent=indent,
        )


def _normalize_top_level_mapping(
    field_name: str,
    value: object,
) -> JsonObject:
    """Normalize a top-level mapping field."""
    if not isinstance(value, dict):
        raise CanonicalNetworkConfigError(
            f"The top-level '{field_name}' field must be an object."
        )
    normalized = deepcopy(value)
    _ensure_json_compatible(normalized, field_name)
    return cast(JsonObject, normalized)


def _normalize_object_list(
    section: str,
    objects: object,
) -> list[JsonObject]:
    """Normalize a canonical list section."""
    if not isinstance(objects, list):
        raise CanonicalNetworkConfigError(
            f"The top-level '{section}' section must be a list."
        )
    return [_normalize_object(section, obj) for obj in objects]


def _normalize_object(
    section: str,
    obj: object,
) -> JsonObject:
    """Normalize a canonical object entry."""
    if not isinstance(obj, dict):
        raise CanonicalNetworkConfigError(
            f"Objects in '{section}' must be dictionaries."
        )

    normalized = cast(JsonObject, deepcopy(obj))
    object_id = normalized.get("id")
    object_type = normalized.get("type")
    if not isinstance(object_id, str) or not object_id:
        raise CanonicalNetworkConfigError(
            f"Objects in '{section}' must include a non-empty string 'id'."
        )
    if not isinstance(object_type, str) or not object_type:
        raise CanonicalNetworkConfigError(
            f"Object {object_id!r} in '{section}' must include a non-empty "
            "string 'type'."
        )

    parameters = normalized.get("parameters", {})
    if not isinstance(parameters, dict):
        raise CanonicalNetworkConfigError(
            f"Object {object_id!r} in '{section}' must use an object for "
            "'parameters'."
        )
    normalized["parameters"] = deepcopy(parameters)

    for field_name, target_section in _REFERENCE_FIELDS.items():
        if field_name not in normalized:
            continue
        value = normalized[field_name]
        if field_name.endswith("_ids"):
            if not isinstance(value, list) or any(
                not isinstance(item, str) or not item for item in value
            ):
                raise CanonicalNetworkConfigError(
                    f"Object {object_id!r} in '{section}' must use a list of "
                    f"non-empty string IDs for '{field_name}' targeting "
                    f"'{target_section}'."
                )
        elif not isinstance(value, str) or not value:
            raise CanonicalNetworkConfigError(
                f"Object {object_id!r} in '{section}' must use a non-empty "
                f"string ID for '{field_name}' targeting '{target_section}'."
            )

    if "participants" in normalized:
        participants = normalized["participants"]
        if not isinstance(participants, list) or any(
            not isinstance(item, str) or not item for item in participants
        ):
            raise CanonicalNetworkConfigError(
                f"Protocol {object_id!r} must use a list of non-empty string "
                "IDs for 'participants'."
            )

    if "ports" in normalized and not isinstance(normalized["ports"], list):
        raise CanonicalNetworkConfigError(
            f"Node {object_id!r} must use a list for 'ports'."
        )
    if "position" in normalized and not isinstance(
        normalized["position"], dict
    ):
        raise CanonicalNetworkConfigError(
            f"Node {object_id!r} must use an object for 'position'."
        )

    _ensure_json_compatible(normalized, f"{section}.{object_id}")
    return normalized


def _ensure_json_compatible(value: object, path: str) -> None:
    """Ensure a value only contains JSON-compatible data."""
    if value is None:
        return
    if isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _ensure_json_compatible(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise CanonicalNetworkConfigError(
                    f"Object keys under '{path}' must be strings."
                )
            _ensure_json_compatible(item, f"{path}.{key}")
        return
    raise CanonicalNetworkConfigError(
        f"Unsupported JSON value at '{path}': {type(value).__name__}."
    )


def _validate_reference_scalar(
    obj: JsonObject,
    *,
    field_name: str,
    target_ids: set[str],
) -> None:
    """Validate a scalar ID reference when present."""
    if field_name not in obj:
        return
    target_id = obj[field_name]
    if not isinstance(target_id, str):
        raise CanonicalNetworkConfigError(
            f"Field '{field_name}' on {obj['id']!r} must be a string."
        )
    if target_id not in target_ids:
        raise CanonicalNetworkConfigError(
            f"Field '{field_name}' on {obj['id']!r} references unknown ID "
            f"{target_id!r}."
        )


def _validate_reference_list(
    obj: JsonObject,
    *,
    field_name: str,
    target_ids: set[str],
) -> None:
    """Validate a list of ID references when present."""
    if field_name not in obj:
        return
    raw_values = obj[field_name]
    if not isinstance(raw_values, list):
        raise CanonicalNetworkConfigError(
            f"Field '{field_name}' on {obj['id']!r} must be a list."
        )
    seen: set[str] = set()
    for item in raw_values:
        if not isinstance(item, str):
            raise CanonicalNetworkConfigError(
                f"Field '{field_name}' on {obj['id']!r} must contain only "
                "string IDs."
            )
        if item in seen:
            raise CanonicalNetworkConfigError(
                f"Field '{field_name}' on {obj['id']!r} contains duplicate "
                f"ID {item!r}."
            )
        if item not in target_ids:
            raise CanonicalNetworkConfigError(
                f"Field '{field_name}' on {obj['id']!r} references unknown "
                f"ID {item!r}."
            )
        seen.add(item)


def _validate_ports(obj: JsonObject) -> None:
    """Validate node port objects when present."""
    if "ports" not in obj:
        return
    ports = obj["ports"]
    if not isinstance(ports, list):
        raise CanonicalNetworkConfigError(
            f"Node {obj['id']!r} must use a list for 'ports'."
        )
    seen_ids: set[str] = set()
    for port in ports:
        if not isinstance(port, dict):
            raise CanonicalNetworkConfigError(
                f"Node {obj['id']!r} contains a non-object port definition."
            )
        port_id = port.get("id")
        port_type = port.get("type")
        if not isinstance(port_id, str) or not port_id:
            raise CanonicalNetworkConfigError(
                f"Node {obj['id']!r} has a port without a non-empty string "
                "'id'."
            )
        if not isinstance(port_type, str) or not port_type:
            raise CanonicalNetworkConfigError(
                f"Port {port_id!r} on node {obj['id']!r} must include a "
                "non-empty string 'type'."
            )
        if port_id in seen_ids:
            raise CanonicalNetworkConfigError(
                f"Node {obj['id']!r} contains duplicate port ID {port_id!r}."
            )
        seen_ids.add(port_id)


def _validate_optional_bool(obj: JsonObject, field_name: str) -> None:
    """Validate an optional boolean field."""
    if field_name not in obj:
        return
    if not isinstance(obj[field_name], bool):
        raise CanonicalNetworkConfigError(
            f"Field '{field_name}' on {obj['id']!r} must be a boolean."
        )


def _sorted_config(config: JsonObject) -> JsonObject:
    """Return a configuration with deterministic object ordering."""
    sorted_config = cast(JsonObject, deepcopy(config))
    for section in _LIST_SECTIONS:
        section_objects = cast(list[JsonObject], sorted_config[section])
        sorted_config[section] = cast(
            JsonValue,
            sorted(section_objects, key=_object_id_sort_key),
        )
    return sorted_config


def _ordered_top_level_config(config: JsonObject) -> JsonObject:
    """Return a JSON-ready config ordered by canonical key layout."""
    ordered: JsonObject = {}
    for key in _TOP_LEVEL_KEY_ORDER:
        if key in config:
            ordered[key] = _ordered_json_value(
                config[key], object_context=False
            )
    for key in sorted(set(config) - set(_TOP_LEVEL_KEY_ORDER)):
        ordered[key] = _ordered_json_value(config[key], object_context=False)
    return ordered


def _ordered_json_value(
    value: JsonValue,
    *,
    object_context: bool,
) -> JsonValue:
    """Recursively order JSON objects for deterministic serialization."""
    if isinstance(value, list):
        return [
            _ordered_json_value(item, object_context=True)
            if isinstance(item, dict)
            else _ordered_json_value(item, object_context=False)
            for item in value
        ]
    if isinstance(value, dict):
        preferred_order = _OBJECT_KEY_ORDER if object_context else ()
        ordered_dict: JsonObject = {}
        for key in preferred_order:
            if key in value:
                ordered_dict[key] = _ordered_json_value(
                    value[key],
                    object_context=False,
                )
        for key in sorted(set(value) - set(preferred_order)):
            ordered_dict[key] = _ordered_json_value(
                value[key],
                object_context=False,
            )
        return ordered_dict
    return value


def _object_id_sort_key(obj: JsonObject) -> str:
    """Return the ID used to order canonical objects."""
    return cast(str, obj["id"])


def _object_with_optional_fields(**kwargs: object) -> dict[str, object]:
    """Build an object while omitting ``None`` values."""
    return {key: value for key, value in kwargs.items() if value is not None}
