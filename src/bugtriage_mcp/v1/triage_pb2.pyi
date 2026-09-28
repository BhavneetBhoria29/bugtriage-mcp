from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Bug(_message.Message):
    __slots__ = ("id", "title", "description", "component", "severity")
    ID_FIELD_NUMBER: _ClassVar[int]
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    COMPONENT_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    id: str
    title: str
    description: str
    component: str
    severity: str
    def __init__(self, id: _Optional[str] = ..., title: _Optional[str] = ..., description: _Optional[str] = ..., component: _Optional[str] = ..., severity: _Optional[str] = ...) -> None: ...

class ComponentProbability(_message.Message):
    __slots__ = ("component", "p")
    COMPONENT_FIELD_NUMBER: _ClassVar[int]
    P_FIELD_NUMBER: _ClassVar[int]
    component: str
    p: float
    def __init__(self, component: _Optional[str] = ..., p: _Optional[float] = ...) -> None: ...

class TriageBugRequest(_message.Message):
    __slots__ = ("title", "description")
    TITLE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    title: str
    description: str
    def __init__(self, title: _Optional[str] = ..., description: _Optional[str] = ...) -> None: ...

class TriageBugResponse(_message.Message):
    __slots__ = ("component", "component_confidence", "component_alternatives", "severity", "severity_probs", "error_codes", "needs_human_review", "possible_duplicates")
    class SeverityProbsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    COMPONENT_FIELD_NUMBER: _ClassVar[int]
    COMPONENT_CONFIDENCE_FIELD_NUMBER: _ClassVar[int]
    COMPONENT_ALTERNATIVES_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_FIELD_NUMBER: _ClassVar[int]
    SEVERITY_PROBS_FIELD_NUMBER: _ClassVar[int]
    ERROR_CODES_FIELD_NUMBER: _ClassVar[int]
    NEEDS_HUMAN_REVIEW_FIELD_NUMBER: _ClassVar[int]
    POSSIBLE_DUPLICATES_FIELD_NUMBER: _ClassVar[int]
    component: str
    component_confidence: float
    component_alternatives: _containers.RepeatedCompositeFieldContainer[ComponentProbability]
    severity: str
    severity_probs: _containers.ScalarMap[str, float]
    error_codes: _containers.RepeatedScalarFieldContainer[str]
    needs_human_review: bool
    possible_duplicates: _containers.RepeatedCompositeFieldContainer[Bug]
    def __init__(self, component: _Optional[str] = ..., component_confidence: _Optional[float] = ..., component_alternatives: _Optional[_Iterable[_Union[ComponentProbability, _Mapping]]] = ..., severity: _Optional[str] = ..., severity_probs: _Optional[_Mapping[str, float]] = ..., error_codes: _Optional[_Iterable[str]] = ..., needs_human_review: _Optional[bool] = ..., possible_duplicates: _Optional[_Iterable[_Union[Bug, _Mapping]]] = ...) -> None: ...

class FindSimilarBugsRequest(_message.Message):
    __slots__ = ("text", "k")
    TEXT_FIELD_NUMBER: _ClassVar[int]
    K_FIELD_NUMBER: _ClassVar[int]
    text: str
    k: int
    def __init__(self, text: _Optional[str] = ..., k: _Optional[int] = ...) -> None: ...

class ScoredBug(_message.Message):
    __slots__ = ("bug", "score")
    BUG_FIELD_NUMBER: _ClassVar[int]
    SCORE_FIELD_NUMBER: _ClassVar[int]
    bug: Bug
    score: float
    def __init__(self, bug: _Optional[_Union[Bug, _Mapping]] = ..., score: _Optional[float] = ...) -> None: ...

class FindSimilarBugsResponse(_message.Message):
    __slots__ = ("hits",)
    HITS_FIELD_NUMBER: _ClassVar[int]
    hits: _containers.RepeatedCompositeFieldContainer[ScoredBug]
    def __init__(self, hits: _Optional[_Iterable[_Union[ScoredBug, _Mapping]]] = ...) -> None: ...

class GetBugRequest(_message.Message):
    __slots__ = ("bug_id",)
    BUG_ID_FIELD_NUMBER: _ClassVar[int]
    bug_id: str
    def __init__(self, bug_id: _Optional[str] = ...) -> None: ...

class SearchLogsRequest(_message.Message):
    __slots__ = ("query", "level", "module", "since", "until", "limit")
    QUERY_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MODULE_FIELD_NUMBER: _ClassVar[int]
    SINCE_FIELD_NUMBER: _ClassVar[int]
    UNTIL_FIELD_NUMBER: _ClassVar[int]
    LIMIT_FIELD_NUMBER: _ClassVar[int]
    query: str
    level: str
    module: str
    since: str
    until: str
    limit: int
    def __init__(self, query: _Optional[str] = ..., level: _Optional[str] = ..., module: _Optional[str] = ..., since: _Optional[str] = ..., until: _Optional[str] = ..., limit: _Optional[int] = ...) -> None: ...

class LogLine(_message.Message):
    __slots__ = ("ts", "level", "module", "code", "message", "vin_suffix")
    TS_FIELD_NUMBER: _ClassVar[int]
    LEVEL_FIELD_NUMBER: _ClassVar[int]
    MODULE_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    VIN_SUFFIX_FIELD_NUMBER: _ClassVar[int]
    ts: str
    level: str
    module: str
    code: str
    message: str
    vin_suffix: str
    def __init__(self, ts: _Optional[str] = ..., level: _Optional[str] = ..., module: _Optional[str] = ..., code: _Optional[str] = ..., message: _Optional[str] = ..., vin_suffix: _Optional[str] = ...) -> None: ...

class SearchLogsResponse(_message.Message):
    __slots__ = ("total_matches", "code_counts", "affected_vehicles", "lines")
    class CodeCountsEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: int
        def __init__(self, key: _Optional[str] = ..., value: _Optional[int] = ...) -> None: ...
    TOTAL_MATCHES_FIELD_NUMBER: _ClassVar[int]
    CODE_COUNTS_FIELD_NUMBER: _ClassVar[int]
    AFFECTED_VEHICLES_FIELD_NUMBER: _ClassVar[int]
    LINES_FIELD_NUMBER: _ClassVar[int]
    total_matches: int
    code_counts: _containers.ScalarMap[str, int]
    affected_vehicles: int
    lines: _containers.RepeatedCompositeFieldContainer[LogLine]
    def __init__(self, total_matches: _Optional[int] = ..., code_counts: _Optional[_Mapping[str, int]] = ..., affected_vehicles: _Optional[int] = ..., lines: _Optional[_Iterable[_Union[LogLine, _Mapping]]] = ...) -> None: ...
