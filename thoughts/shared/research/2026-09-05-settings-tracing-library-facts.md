# pydantic-settings / logfire / OpenTelemetry / pydantic-ai library facts for Settings + local JSONL tracing (2026-09-05)

Research against primary sources only: the installed package source under `.venv/lib/python3.12/site-packages/` (abbreviated `SP/` below; every path is relative to it unless it starts with `/`), the pydantic-settings docs page, and probe scripts run locally with `uv run --no-sync python` from the repo root with `LOGFIRE_TOKEN` unset. Installed versions checked: pydantic-settings 2.15.0, python-dotenv 1.2.3, pydantic 2.13.5, pydantic-core 2.46.5, logfire 5.0.0, opentelemetry-sdk/api 1.44.0, pydantic-ai-slim 2.40.0 (`SP/*.dist-info`). Summary: `Settings(_env_file=path)` is the init argument, `_env_file=None` disables file reading, and without an `env_file` in `model_config` nothing is read from CWD; precedence is init kwargs > `os.environ` > dotenv > secrets dir > field defaults. Unknown dotenv keys raise `ValidationError(extra_forbidden)` under the default `extra='forbid'`; `extra='ignore'` (or `dotenv_filtering='only_existing'`) makes them harmless. A blank `LOGFIRE_TOKEN=` reaches a `str | None` field as `''`; `env_ignore_empty=True` is the knob that turns blanks into "unset" for every field (falls back to lower-priority sources/defaults); `env_parse_none_str=''` produces an explicit `None`, which breaks blank `int`/`Decimal` fields with `int_type`/`decimal_type`. python-dotenv strips whitespace around unquoted values but keeps it inside quotes; real environment variables are never stripped. logfire 5.0.0's `configure(send_to_logfire='if-token-present', token=None, console=False, metrics=False, additional_span_processors=[SimpleSpanProcessor(exporter)])` makes zero network calls, writes no `.logfire/` directory and emits no warnings; if a token IS present it spawns a `check_logfire_token` thread that GETs `/v1/info` and starts OTLP exporters, so tests must never see one. Additional processors are wrapped by `MainSpanProcessorWrapper` (so attribute values matching the scrub patterns, e.g. any key containing `api_key`/`secret`/`auth`/`session`/`logfire_token`, arrive as `[Scrubbed due to '...']`), but pending spans never reach a custom exporter in 5.0.0 (they are only routed to logfire's own/console/test exporters). `with logfire.span(...)` sets status `ERROR` with description `ValueError: boom`, adds an `exception` event, `logfire.level_num=17` and `logfire.exception.fingerprint` when an exception escapes. Under `logfire.instrument_pydantic_ai()` (default instrumentation version 5) an `Agent(TestModel(), name='probe_agent').run_sync('hello')` yields two spans in one trace: root `invoke_agent probe_agent` (attributes `agent_name` and `gen_ai.agent.name` both `'probe_agent'`) and child `chat test`; the span name `agent run` only exists for instrumentation version 2. `configure()` may be called again without a warning (it rebuilds the pipeline and drops old processors); `local=True` never touches the global tracer provider.

## A. pydantic-settings 2.15.0

### A1. Loading a specific env file at instantiation

- The init argument is `_env_file`: `def __init__(__pydantic_self__, _case_sensitive=None, ..., _env_file: DotenvType | None = ENV_FILE_SENTINEL, _env_file_encoding=None, _env_ignore_empty=None, ..., _env_parse_none_str=None, ..., **values)`. `DotenvType = Path | str | Sequence[Path | str]`, so a `Path` or a list of paths is accepted. Source: `SP/pydantic_settings/main.py:193-224`; `SP/pydantic_settings/sources/types.py:37`.
- Docstring: "`_env_file`: The env file(s) to load settings values from. Defaults to `Path('')`, which means that the value from `model_config['env_file']` should be used. You can also pass `None` to indicate that environment variables should not be loaded from an env file." Source: `SP/pydantic_settings/main.py:148-150`.
- Resolution: `env_file = _env_file if _env_file != ENV_FILE_SENTINEL else cls.model_config.get('env_file')` with `ENV_FILE_SENTINEL: DotenvType = Path('')`. `BaseSettings.model_config` defaults `env_file=None`. Source: `SP/pydantic_settings/main.py:332`, `:625`; `SP/pydantic_settings/sources/types.py:50`.
- `DotEnvSettingsSource._read_env_files`: `if env_files is None: return {}`; otherwise each path is `Path(env_file).expanduser()` and read only `if env_path.is_file() or env_path.is_fifo()`, a missing file is skipped silently (debug log only). Reading goes through `dotenv_values(file_path, encoding=encoding or 'utf8')`, always with an explicit path, so python-dotenv's `find_dotenv()` CWD search (which only runs when `dotenv_path is None and stream is None`) is never triggered. Source: `SP/pydantic_settings/sources/providers/dotenv.py:85, 100-120`; `SP/dotenv/main.py:438-463`.
- Docs: "Passing a file path via the `_env_file` keyword argument on instantiation (method 2) will override the value (if any) set on the `model_config` class." and "You can also use the keyword argument override to tell Pydantic not to load any file at all (even if one is set in the `model_config` class) by passing `None` as the instantiation keyword argument, e.g. `settings = Settings(_env_file=None)`." Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ ("Dotenv (.env) support"), accessed 2026-09-05.
- Probe (CWD containing a `.env` with `RA_MAX_ITERATIONS=99`, field default 3): no `_env_file` and no `env_file` in config -> `3`; `_env_file=None` -> `3`; `model_config env_file='.env'` -> `99`; `env_file='.env'` plus `_env_file=None` -> `3`. Run locally 2026-09-05 (`scratchpad/probe_settings.py`).

### A2. Source precedence

- Default hook returns `(init_settings, env_settings, dotenv_settings, file_secret_settings)`; `_settings_init_sources` appends `(default_settings,)`. Source: `SP/pydantic_settings/main.py:265-286, 442-448`.
- Merge loop: `for source in sources: ... state = deep_update(source_state, state)`, i.e. the accumulated state (earlier = higher priority) overwrites the current source's values; the resulting order is init kwargs > environment > dotenv > secrets dir > defaults. Source: `SP/pydantic_settings/main.py:485-506`.
- Docs: "environment variables will always take priority over values loaded from a dotenv file". Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ ("Dotenv (.env) support"), accessed 2026-09-05.
- Probe: env `RA_MAX_ITERATIONS=42` + dotenv `7` -> `42`; init `ra_max_iterations=1` + env `42` + dotenv `7` -> `1`. An explicit init kwarg `openrouter_api_key=None` also wins over env `from-env` (init `None` is a value, not "unset"). Run locally 2026-09-05.

### A3. Extra keys in the dotenv file

- `BaseSettings.model_config` sets `extra='forbid'`. Source: `SP/pydantic_settings/main.py:618`.
- `DotEnvSettingsSource.__call__`: after the field pass, `is_extra_allowed = self.config.get('extra') != 'forbid'`, then every dotenv key that matched no field is added to the returned data regardless (`data[normalized_env_name] = env_value` when allowed, else `data[env_name] = env_value`), so pydantic sees it and applies its own `extra` policy: `forbid` -> `ValidationError` type `extra_forbidden`; `ignore` -> dropped; `allow` -> kept (with `env_prefix` stripped). Blank extras (`if not env_value ... continue`) are skipped before this. Source: `SP/pydantic_settings/sources/providers/dotenv.py:143-180`.
- The 2.x knob that changes this is `dotenv_filtering: Literal['match_prefix', 'only_existing']` in `SettingsConfigDict`: `'only_existing'` returns only field matches ("behaves like the EnvSettingsSource"), `'match_prefix'` adds prefix matches only. Default is `None` (the extra-passing behaviour above). Source: `SP/pydantic_settings/sources/providers/dotenv.py:57-59, 122-141`; `SP/pydantic_settings/sources/types.py:44`; `SP/pydantic_settings/main.py:56`.
- Docs: "Pydantic settings consider `extra` config in case of dotenv file. It means if you set the `extra=forbid` (default) on `model_config` and your dotenv file contains an entry for a field that is not defined in settings model, it will raise `ValidationError`", "This behaviour can be customized by using the setting `dotenv_filtering` ... `'only_existing'`: only the variables that have a corresponding field will be passed to the model.", "For compatibility with pydantic 1.x BaseSettings you should use `extra=ignore`". Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ ("Dotenv (.env) support"), accessed 2026-09-05.
- Probe: dotenv with `UNKNOWN_KEY=zzz` -> `ValidationError [('extra_forbidden', ('unknown_key',))]` (note the lower-cased loc); with `SettingsConfigDict(extra='ignore')` it loads. Conclusion: `extra='ignore'` is still the right knob in 2.15; `dotenv_filtering='only_existing'` is the stricter alternative that keeps `extra='forbid'` for init kwargs. Run locally 2026-09-05.

### A4. Blank value `LOGFIRE_TOKEN=` for `str | None = None`

- python-dotenv: `parse_value` returns `""` when the character after `=` is end-of-input or a newline; a bare key without `=` yields `None` (`Binding(value=None)`, docstring: "`foo` alone results in `{"foo": None}`"). Source: `SP/dotenv/parser.py:131-141, 143-170`; `SP/dotenv/main.py:448-450`.
- pydantic-settings passes values through `parse_env_vars(env_vars, case_sensitive, ignore_empty, parse_none_str)` = `{key: _parse_env_none_str(v, parse_none_str) for k, v in env_vars.items() if not (ignore_empty and v == '')}`. So by default `''` survives and the field receives `''` (a `str`). Source: `SP/pydantic_settings/sources/utils.py:64-74`; probe: `logfire_token repr: '' type: str`.
- `env_parse_none_str`: `_parse_env_none_str(value, parse_none_str)` returns `EnvNoneType(value)` when `value == parse_none_str and parse_none_str is not None`; `PydanticBaseEnvSettingsSource.__call__` then turns `EnvNoneType` into a literal `None` in the source's output (`if self.env_parse_none_str is not None: ... elif isinstance(field_value, EnvNoneType): field_value = None`). It applies to every field, and the explicit `None` is a real value that shadows lower-priority sources. Source: `SP/pydantic_settings/sources/utils.py:60-61`; `SP/pydantic_settings/sources/types.py:24-25`; `SP/pydantic_settings/sources/base.py:614-619`. Note `_settings_init_sources` does `cli_parse_none_str = cli_parse_none_str if not env_parse_none_str else env_parse_none_str`, so `''` (falsy) does not leak into the CLI source. Source: `SP/pydantic_settings/main.py:358`.
- `env_ignore_empty` (default `False`): drops `''` entries before field matching, so the field falls through to the next source or its default. Docs: "By default environment variables are parsed verbatim, including if the value is empty. You can choose to ignore empty environment variables by setting the `env_ignore_empty` config setting to `True`." Source: `SP/pydantic_settings/main.py:627`; `SP/pydantic_settings/sources/utils.py:73`; https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ ("Parsing environment variable values"), accessed 2026-09-05.
- Probe with dotenv `LOGFIRE_TOKEN=`, `RA_MAX_ITERATIONS=`, `RA_BUDGET_USD=` (fields `str | None = None`, `int = 3`, `Decimal = Decimal('1')`):
  - default config -> `ValidationError [int_parsing (ra_max_iterations), decimal_parsing (ra_budget_usd)]`, token would be `''`.
  - `env_ignore_empty=True` -> `logfire_token=None, ra_max_iterations=3, ra_budget_usd=Decimal('1')`; with env `OPENROUTER_API_KEY=''` and dotenv `from-dotenv` the dotenv value wins (`'from-dotenv'`).
  - `env_parse_none_str=''` -> `logfire_token=None` but `ValidationError [int_type, decimal_type]` for the blank numeric fields.
  - `@field_validator('logfire_token', mode='before')` mapping `''` -> `None` -> `logfire_token=None`, numeric blanks still fail with `int_parsing`/`decimal_parsing` (validator only covers the listed fields).
  Run locally 2026-09-05 (`scratchpad/probe_settings.py`, `probe_blank.py`).
- Recommendation: `SettingsConfigDict(env_ignore_empty=True)` is the one-line, all-fields answer ("blank = unset", falls back to defaults, does not mask lower-priority sources oddly) and matches the documented purpose of the knob. Use a `mode='before'` validator only if a blank must be distinguishable from unset for a specific field. Avoid `env_parse_none_str=''`: it yields explicit `None` for numeric fields.

### A5. Whitespace in dotenv values

- `parse_binding` reads the key, then `_equal_sign = (=[^\S\r\n]*)`, which consumes the `=` and any spaces/tabs after it. Unquoted values: `parse_unquoted_value` returns `re.sub(r"\s+#.*", "", part).rstrip()`, i.e. an inline comment needs at least one whitespace before `#`, and trailing whitespace is stripped. Quoted values (`'...'` / `"..."`) are taken verbatim between the quotes (escape sequences decoded), so inner spaces survive. Source: `SP/dotenv/parser.py:23, 126-141, 143-170`.
- Probe `dotenv_values`: `OPENROUTER_API_KEY= sk-or-test ` -> `'sk-or-test'`; `OPENROUTER_API_KEY=" sk-or-test "` -> `' sk-or-test '`; `RA_MAX_ITERATIONS=5 # trailing comment` -> `'5'`; `RA_BUDGET_USD=5#nospace` -> `'5#nospace'` (then `decimal_parsing` error); `export BARE` -> `None`. Run locally 2026-09-05 (`scratchpad/probe_quotes.py`).
- pydantic-settings does not strip or otherwise post-process values: `parse_env_vars` only lower-cases keys and applies the none-str/ignore-empty rules (`_get_env_var_key(key, case_sensitive) = key if case_sensitive else key.lower()`). Source: `SP/pydantic_settings/sources/utils.py:56-74`.
- Real environment variables are not stripped either: `os.environ['OPENROUTER_API_KEY'] = ' sk '` -> field value `' sk '`. Numeric validators tolerate surrounding whitespace (`' 5'`, `'5 '` -> `Decimal('5')`; `' 7'` -> `7`), `str` fields keep it. Run locally 2026-09-05.

### A6. Case handling without `env_prefix`

- Defaults: `case_sensitive=False`, `env_prefix=''`. Source: `SP/pydantic_settings/main.py:621-622`.
- Field-side: `_extract_field_info` registers `(field_name, self._apply_case_sensitive(env_prefix + field_name), ...)` with `_apply_case_sensitive(value) = value.lower() if not self.case_sensitive else value`. Env-side: both `os.environ` and dotenv keys go through `_get_env_var_key`, which lower-cases when not case-sensitive. So `OPENROUTER_API_KEY` (env) and `RA_MAX_ITERATIONS` (dotenv) both match `openrouter_api_key` / `ra_max_iterations`. Source: `SP/pydantic_settings/sources/base.py:421-422, 472-474`; `SP/pydantic_settings/sources/utils.py:56-57`; `SP/pydantic_settings/sources/providers/env.py:86-94` (also forces case-insensitive on Windows).
- Docs: "By default, environment variable names are case-insensitive." Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ ("Environment variable names"), accessed 2026-09-05.
- Probe: env `OPENROUTER_API_KEY=from-env` -> `openrouter_api_key='from-env'`; dotenv `RA_MAX_ITERATIONS=7` -> `ra_max_iterations=7`. Run locally 2026-09-05.

### A7. String -> `int` / `Decimal` coercion

- Non-strict mode: the source hands the raw string to pydantic's lax validation; `_coerce_env_val_strict` only pre-coerces when `strict=True` or the annotation contains strict types. Source: `SP/pydantic_settings/sources/providers/env.py:340-373`.
- Probe results (pydantic 2.13.5): `Decimal` field: `'5'` -> `Decimal('5')`, `'5.0'` -> `Decimal('5.0')` (equal to `Decimal('5')` but `str()` differs: `'5'` vs `'5.0'`), `'1e2'` -> `Decimal('1E+2')`, `'abc'` and `''` -> `decimal_parsing`. `int` field: `'7'`, `'7.0'`, `' 7'` -> `7`; `'7.5'` and `''` -> `int_parsing`. Run locally 2026-09-05.
- Pitfalls: blank strings are errors, not defaults (see A4); `Decimal` keeps the textual exponent/scale of the input, so normalise (`.quantize`/`.normalize()`) before comparing string forms; `RA_BUDGET_USD=5#nospace` is not a comment (A5).

## B. logfire 5.0.0 + opentelemetry-sdk 1.44.0

### B1. `logfire.configure(...)` signature

- Keyword-only signature (all parameters): `configure(*, local: bool = False, send_to_logfire: bool | Literal['if-token-present'] | None = None, token: str | list[str] | None = None, api_key: str | None = None, service_name: str | None = None, service_version: str | None = None, environment: str | None = None, resource_attributes: Mapping[str, Any] | None = None, console: ConsoleOptions | Literal[False] | None = None, config_dir: Path | str | None = None, data_dir: Path | str | None = None, additional_span_processors: Sequence[SpanProcessor] | None = None, metrics: MetricsOptions | Literal[False] | None = None, scrubbing: ScrubbingOptions | Literal[False] | None = None, inspect_arguments: bool | None = None, sampling: SamplingOptions | None = None, min_level: int | LevelName | None = None, add_baggage_to_attributes: bool = True, code_source: CodeSource | None = None, variables: VariablesOptions | LocalVariablesOptions | None = None, distributed_tracing: bool | None = None, advanced: AdvancedOptions | None = None) -> Logfire`. Source: `SP/logfire/_internal/config.py:498-522`.
- `send_to_logfire`: "Defaults to the `LOGFIRE_SEND_TO_LOGFIRE` environment variable if set, otherwise defaults to `True`. If `if-token-present` is provided, logs will only be sent if a token is present." The actual code default is `'PYTEST_VERSION' not in os.environ`, i.e. `False` under pytest. Source: `SP/logfire/_internal/config.py:528-531`; `SP/logfire/_internal/config_params.py:52-56`.
- `token`: "Defaults to the `LOGFIRE_TOKEN` environment variable (supports comma-separated tokens)." Loaded as `self.token = normalize_token(token) or normalize_token(param_manager.load_param('token', None))`. Source: `SP/logfire/_internal/config.py:533-536, 757`; `SP/logfire/_internal/config_params.py:60`.
- `console`: "If `None` uses the `LOGFIRE_CONSOLE_*` environment variables, otherwise defaults to `ConsoleOption(colors='auto', indent_spans=True, include_timestamps=True, include_tags=True, verbose=False)`. If `False` disables console output. It can also be disabled by setting `LOGFIRE_CONSOLE` environment variable to `false`." Off: `console=False` (then `if self.console:` skips the console exporter). On: pass `logfire.ConsoleOptions(colors='auto', span_style='show-parents', include_timestamps=True, include_tags=True, verbose=False, min_log_level='info', show_project_link=True, output=None)` (all fields optional) or leave `None`. `ConsoleOptions` is exported from `logfire`. Source: `SP/logfire/_internal/config.py:565-567, 163-186, 786-800, 1182-1199`; `SP/logfire/_internal/config_params.py:76`; `SP/logfire/__init__.py:18, 132`.
- `additional_span_processors`: "Span processors to use in addition to the default processor which exports spans to Logfire's API." Source: `SP/logfire/_internal/config.py:573`.
- `service_name`: "Defaults to the `LOGFIRE_SERVICE_NAME` environment variable." (also `OTEL_SERVICE_NAME`, default `''`). Source: `SP/logfire/_internal/config.py:542-544`; `SP/logfire/_internal/config_params.py:64`.
- `metrics`: "Set to `False` to disable sending all metrics, or provide a `MetricsOptions` object". With `False`, `metric_readers` stays `None` and a `NoOpMeterProvider` is installed. Source: `SP/logfire/_internal/config.py:574-575, 1200-1202, 1417-1436`.
- `scrubbing`: "Options for scrubbing sensitive data. Set to `False` to disable." `False` -> `NOOP_SCRUBBER`. Source: `SP/logfire/_internal/config.py:576, 776-784`.
- `inspect_arguments`: f-string magic; "If `None` uses the `LOGFIRE_INSPECT_ARGUMENTS` environment variable. Defaults to `True` if and only if the Python version is at least 3.11." Source: `SP/logfire/_internal/config.py:577-582`; `SP/logfire/_internal/config_params.py:105`.
- `local`: "If `True`, configures and returns a `Logfire` instance that is not the default global instance." Implementation: `config = LogfireConfig()` instead of `GLOBAL_CONFIG`, returns `Logfire(config=config)`. Source: `SP/logfire/_internal/config.py:526-527, 608-611, 639-642`.
- `data_dir`: "Directory to store credentials, and logs. If `None` uses the `LOGFIRE_CREDENTIALS_DIR` environment variable, otherwise defaults to `'.logfire'`." Source: `SP/logfire/_internal/config.py:572`; `SP/logfire/_internal/config_params.py:74`.

### B2. Token discovery and network behaviour

- Lookup order: explicit `token` argument, else `LOGFIRE_TOKEN` env var (comma-separated list allowed), else, only when `send_to_logfire` is truthy, the credentials file `<data_dir>/logfire_credentials.json` via `LogfireCredentials.load_creds_file(self.data_dir)` (`self.token = self.token or credentials.token`). Source: `SP/logfire/_internal/config.py:757, 1204-1231, 143`; `SP/logfire/_internal/config_params.py:60`.
- Interactive project creation (`LogfireCredentials.initialize_project`, prompts on stderr) runs only `if not self.token and self.send_to_logfire is True and credentials is None` with the comment "we only do this if `send_to_logfire` is explicitly `True`, not 'if-token-present'". Source: `SP/logfire/_internal/config.py:1218-1224, 2177-2229`.
- With `'if-token-present'` and no token anywhere: the `if self.token:` block is skipped entirely, so no exporter, no thread, no warning, nothing written. Source: `SP/logfire/_internal/config.py:1233-1298`.
- When a token IS present (any `send_to_logfire` truthy): a `Thread(target=check_tokens, name='check_logfire_token')` calls `LogfireCredentials.from_token`, which does `session.get(urljoin(base_url, '/v1/info'), ...)` and `warnings.warn(f'Logfire API is unreachable, you may have trouble sending data. Error: {e}')` on failure; OTLP span/metric/log exporters pointing at `<base_url>/v1/traces` etc. are also installed. Source: `SP/logfire/_internal/config.py:1253-1298, 1648-1656, 1867-1895`.
- Probe (`requests` adapter and `socket.connect` monkeypatched to record and fail; CWD = empty temp dir): `send_to_logfire='if-token-present'`, no token -> `warnings: []`, `network calls: []`, `.logfire dir created: False`. `send_to_logfire=False` -> identical. `'if-token-present'` with a fake `pylf_v1_us_...` token -> background `check_logfire_token` thread attempted `GET .../v1/info` and the OTLP exporter raised "Exception while exporting Span." Conclusion: never let a token reach `configure` in tests (unset `LOGFIRE_TOKEN`, pass `token=None`, and prefer `send_to_logfire=False` in the test suite). Run locally 2026-09-05 (`scratchpad/probe_network.py`).
- Creating spans before `configure()` emits `LogfireNotConfiguredWarning` ("... until `logfire.configure()` has been called. Set the environment variable LOGFIRE_IGNORE_NO_CONFIG=1 ..."). Source: `SP/logfire/_internal/config.py:1638-1646`.

### B3. How `additional_span_processors` are wired; pending spans

- Each additional processor is passed to the local `add_span_processor`, which appends it to `main_multiprocessor` (a `SynchronousMultiSpanProcessor`). It is also added to `processors_with_pending_spans` only if `getattr(span_processor, 'span_exporter', None)` is an instance of `(TestExporter, RemovePendingSpansExporter, SimpleConsoleSpanExporter)`, which a custom exporter is not. Source: `SP/logfire/_internal/config.py:1154-1178`.
- The SDK provider gets a single root processor: `CheckSuppressInstrumentationProcessorWrapper(MainSpanProcessorWrapper(root_processor, self.scrubber))`, where `root_processor` is `main_multiprocessor` (no tail sampling). `MainSpanProcessorWrapper.on_end` rebuilds the span from `span_to_dict(span)` after `_tweak_*`, `_set_error_level_and_status`, `_default_gen_ai_response_model` and `self.scrubber.scrub_span(span_dict)`, then forwards `ReadableSpan(**span_dict)`. So yes: additional processors receive scrubbed, message-formatted spans. Source: `SP/logfire/_internal/config.py:1370-1374`; `SP/logfire/_internal/exporters/processor_wrapper.py:60-85`; `SP/logfire/_internal/utils.py:161-176`.
- Pending spans are produced by `PendingSpanProcessor.on_start`, which builds a `ReadableSpan` with `attributes = {**attributes, 'logfire.span_type': 'pending_span', 'logfire.pending_parent_id': format_span_id(real parent or 0)}`, `context` = a fresh span id in the same trace, `parent` = the real span's context, `start_time == end_time`, and calls `processor.on_end(pending_span)`. That processor is `MainSpanProcessorWrapper(pending_multiprocessor, ...)` containing only `processors_with_pending_spans`. Custom exporters therefore never see pending spans in 5.0.0. Source: `SP/logfire/_internal/tracer.py:339-404`; `SP/logfire/_internal/config.py:1342-1350`.
- Defensive recognition anyway (mirrors logfire's own `RemovePendingSpansExporter`): `(span.attributes or {}).get('logfire.span_type') == 'pending_span'` -> skip. Other values of `logfire.span_type`: `'span'` (stamped by `_ProxyTracer.start_span`), `'log'` (zero-duration spans emitted by `logfire.info(...)` etc., which DO reach additional processors). Source: `SP/logfire/_internal/exporters/remove_pending.py:15-30`; `SP/logfire/_internal/tracer.py:298`; `SP/logfire/_internal/main.py:790`; `SP/logfire/_internal/constants.py:106-109`.
- Probe: an in-memory exporter behind `SimpleSpanProcessor` received `pending spans seen: 0` across `logfire.span` nesting and a pydantic-ai run. Run locally 2026-09-05 (`scratchpad/probe_logfire_ai.py`).
- Scrubbing consequence for a JSONL exporter: attribute keys or string values matching `DEFAULT_PATTERNS` (`password`, `passwd`, `secret`, `auth(?!ors?\b)`, `credential`, `private[._ -]?key`, `api[._ -]?key`, `session`, `cookie`, `logfire[._ -]?token`, `pylf_v\d+_`, `csrf|xsrf|jwt|ssn` ...) are replaced by `f'[Scrubbed due to {matched_substring!r}]'` and a `logfire.scrubbed` JSON attribute is added; `SAFE_KEYS` (e.g. `logfire.msg`, `code.*`, `exception.*`) are exempt. Probe: `logfire.span('iteration', openrouter_api_key='sk-or-abc', note='my secret plan')` arrived as `openrouter_api_key="[Scrubbed due to 'api_key']"`, `note="[Scrubbed due to 'secret']"`, plus `logfire.scrubbed='[{"path": ["attributes", "openrouter_api_key"], ...}]'`. Disable with `scrubbing=False` or whitelist via `ScrubbingOptions(callback=...)`. Source: `SP/logfire/_internal/scrubbing.py:38-70, 120-160, 221-237, 311-353`; run locally 2026-09-05 (`scratchpad/probe_scrub.py`).

### B4. `SpanExporter`, `SimpleSpanProcessor`, `BatchSpanProcessor`

- `class SpanExportResult(Enum): SUCCESS = 0; FAILURE = 1`. `class SpanExporter:` with `export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult`, `shutdown(self) -> None`, `force_flush(self, timeout_millis: int = 30000) -> bool`. The base methods are no-op stubs, so a subclass only needs `export`. Source: `SP/opentelemetry/sdk/trace/export/__init__.py:52-90`.
- `SimpleSpanProcessor(span_exporter, *, meter_provider=None)`: `on_start` is `pass`; `on_end(span)` returns early for unsampled spans, then calls `self.span_exporter.export((span,))` synchronously inside a suppress-instrumentation context, catching any `Exception` and logging `"Exception while exporting Span."` (the exception never propagates to user code); `shutdown()` calls `span_exporter.shutdown()`; `force_flush` just returns `True`. So the file is written before `with logfire.span(...)` returns. Source: `SP/opentelemetry/sdk/trace/export/__init__.py:92-143`.
- `BatchSpanProcessor(span_exporter, max_queue_size=None, schedule_delay_millis=None, max_export_batch_size=None, export_timeout_millis=None, *, meter_provider=None)`: queues in `on_end` (`self._batch_processor.emit(span)`) and exports from a worker thread; tunable via `OTEL_BSP_SCHEDULE_DELAY`, `OTEL_BSP_MAX_QUEUE_SIZE`, `OTEL_BSP_MAX_EXPORT_BATCH_SIZE`, `OTEL_BSP_EXPORT_TIMEOUT`; needs `force_flush()`/`shutdown()` before reading the file. Source: `SP/opentelemetry/sdk/trace/export/__init__.py:146-236`.
- Flushing from logfire: `logfire.force_flush(timeout_millis: int = 3_000) -> bool` and `logfire.shutdown(timeout_millis: int = 30_000, flush: bool = True) -> bool` (module-level aliases of the default instance). Source: `SP/logfire/_internal/main.py:912-921, 2485-2497`; `SP/logfire/__init__.py:37, 73`.

### B5. `ReadableSpan` fields for a flat JSON record

- Properties: `name: str`, `context` (`SpanContext | None`, also `get_span_context()`), `parent: SpanContext | None`, `kind: SpanKind`, `start_time: int | None`, `end_time: int | None` (nanoseconds since epoch), `status: Status`, `attributes` (returns `MappingProxyType(self._attributes or {})`), `events: Sequence[Event]`, `links`, `resource: Resource`, `instrumentation_scope: InstrumentationScope | None`. Source: `SP/opentelemetry/sdk/trace/__init__.py:407-523`.
- `SpanContext.trace_id` / `.span_id` are ints; the SDK's own `to_json` formats the parent as `f"0x{trace_api.format_span_id(...)}"`. Helpers: `format_trace_id(trace_id: int) -> str` (`032x`) and `format_span_id(span_id: int) -> str` (`016x`) in `opentelemetry.trace`. Source: `SP/opentelemetry/sdk/trace/__init__.py:526-530`; `SP/opentelemetry/trace/span.py:599-618`.
- `StatusCode` enum: `UNSET = 0`, `OK = 1`, `ERROR = 2`; `Status(status_code=StatusCode.UNSET, description: str | None = None)` with `.status_code`, `.description`, `.is_ok`, `.is_unset`; a description is only kept when the code is `ERROR`. Successful spans stay `UNSET` (probe: pydantic-ai spans report `status: UNSET`). Source: `SP/opentelemetry/trace/status.py:10-20, 23-66`.
- Attribute value types: `AttributeValue = str | bool | int | float | Sequence[str] | Sequence[bool] | Sequence[int] | Sequence[float]`; the SDK's validator additionally accepts `bytes` (`_VALID_ATTR_VALUE_TYPES = (bool, str, bytes, int, float)`), so `json.dumps(dict(span.attributes), default=str)` is the safe form. Sequences are stored as tuples. Source: `SP/opentelemetry/util/types.py:20-30`; `SP/opentelemetry/attributes/__init__.py:14, 40-62`.
- Exception details live in `span.events` (name `exception`, attributes `exception.type`, `exception.message`, `exception.stacktrace`, `exception.escaped`), not in `span.attributes`. Source: `SP/opentelemetry/sdk/trace/__init__.py:1064-1090`.

### B6. `logfire.span(...)` as a context manager: exceptions and standard attributes

- Signature: `span(msg_template: str, /, *, _tags=None, _span_name=None, _level=None, _links=(), _span_kind=SpanKind.INTERNAL, **attributes: Any) -> LogfireSpan`; "Attributes starting with an underscore are not allowed." Source: `SP/logfire/_internal/main.py:566-600`.
- `LogfireSpan.__exit__`: `if self._span and self._span.is_recording() and isinstance(exc_value, BaseException): self._span.record_exception(exc_value, escaped=True)` then `_end()`. `record_exception(..., escaped=True)` does `set_exception_status(span, exception)` -> `Status(StatusCode.ERROR, description=f'{exception.__class__.__name__}: {exception}')`, sets `logfire.level_num`/`logfire.level_name` to error (`17`), computes `logfire.exception.fingerprint`, and finally calls the SDK `span.record_exception` (adds the `exception` event). For `pydantic.ValidationError` it also stores `exception.logfire.data` (JSON). Source: `SP/logfire/_internal/main.py:3190-3194`; `SP/logfire/_internal/tracer.py:203-218, 423-486, 503-508`; `SP/logfire/_internal/constants.py:22, 133, 185`.
- Probe: `with logfire.span('outer {x}', x=1, ...): with logfire.span('inner'): raise ValueError('boom')` -> both spans `status: ERROR`, `status_desc: 'ValueError: boom'`, `events: ['exception']`, `logfire.level_num = 17`; the outer span additionally had `logfire.exception.fingerprint`. Run locally 2026-09-05.
- Attributes logfire attaches: `_span` merges `get_user_stack_info()` (`code.filepath` relative to CWD when possible, `code.lineno`, and `code.function` unless the caller is module-level code) with the user attributes, then `logfire.msg_template`, `logfire.msg` (formatted), `logfire.json_schema` (only when user attributes exist; a JSON string like `{"type":"object","properties":{"x":{},...}}`), `logfire.tags` (only if tags), `logfire.span_type='span'`, and `logfire.level_num`/`level_name` only when `_level` is given or an exception escapes. Source: `SP/logfire/_internal/main.py:211-283`; `SP/logfire/_internal/stack_info.py:17-20, 55-90`; `SP/logfire/_internal/tracer.py:298`; `SP/logfire/_internal/constants.py:84-124`.
- Value types: user attributes pass through `prepare_otlp_attribute`: `Enum` -> JSON string; `int` kept unless `> OTLP_MAX_INT_SIZE` (then `str`); non-finite floats -> `str`; `str`/`bool` kept; everything else (lists, dicts, dataclasses, Decimal, datetime...) -> `logfire_json_dumps(value)`, i.e. a JSON *string*. Probe: `tags_like=['a','b']` arrived as `'["a","b"]'`; `json.dumps(dict(span.attributes))` succeeded for every span. So values are always JSON-serialisable primitives, and complex values are pre-serialised strings (parse them if you want nested JSON in the record). Source: `SP/logfire/_internal/main.py:3353-3382`; run locally 2026-09-05.

### B7. Calling `configure()` more than once; global provider

- `LogfireConfig.configure` takes the lock, sets `self._initialized = False`, reloads parameters and calls `initialize()` -> `_initialize()`, which builds a new `SDKTracerProvider`, calls `self._tracer_provider.shutdown()` (shuts down the previous SDK provider and its processors) and `set_provider(...)` on the `ProxyTracerProvider`, re-pointing every existing `_ProxyTracer`. There is no "already configured" warning or error. Comment: "if this takes longer than 100ms you should call `logfire.shutdown` before reconfiguring". Source: `SP/logfire/_internal/config.py:1013-1040, 1131-1153, 1438-1443`; `SP/logfire/_internal/tracer.py:65-69`.
- Global OTel providers are set exactly once per process: `if self is GLOBAL_CONFIG and not self._has_set_providers: self._has_set_providers = True; trace.set_tracer_provider(self._tracer_provider); set_meter_provider(...); set_logger_provider(...)` ("This ensures that we only call OTEL's global set_tracer_provider once to avoid warnings."). The object installed is the long-lived `ProxyTracerProvider`, so later reconfigurations swap the SDK provider behind it. `local=True` uses a fresh `LogfireConfig()` which is never `GLOBAL_CONFIG`, so it never touches the global provider. Source: `SP/logfire/_internal/config.py:983, 1463-1467, 608-611`.
- Probe: second `configure(send_to_logfire=False, console=False, additional_span_processors=[SimpleSpanProcessor(exp2)])` -> `warnings: []`, same `Logfire` instance returned, `otel_trace.get_tracer_provider()` unchanged (still the proxy), a span created afterwards reached only `exp2` (the first exporter got nothing). `configure(local=True, ...)` -> a distinct `Logfire` instance whose spans went only to its own exporter; global provider unchanged. Run locally 2026-09-05.
- Practical rule: one `configure` per process is the intended use; a second call is safe and replaces the pipeline (old additional processors are dropped, not accumulated). For per-test isolation, `local=True` plus `local_instance.span(...)` avoids touching the global default instance, but pydantic-ai instrumentation through `logfire.instrument_pydantic_ai()` uses the *default* instance's provider unless you call `local_instance.instrument_pydantic_ai()`.

## C. pydantic-ai 2.40.0 instrumentation with logfire

### C1. `logfire.instrument_pydantic_ai()`

- Signature: `instrument_pydantic_ai(self, obj: Agent | Model | None = None, /, *, include_binary_content: bool | None = None, include_content: bool | None = None, version: Literal[1, 2, 3, 4, 5] | None = None, event_mode: Literal['attributes', 'logs'] | None = None, **kwargs: Any) -> Model | None`. Module-level `logfire.instrument_pydantic_ai` is bound to the default instance. Source: `SP/logfire/_internal/main.py:1125-1165`; `SP/logfire/__init__.py:41`.
- Implementation: builds `InstrumentationSettings(tracer_provider=logfire_instance.config.get_tracer_provider(), meter_provider=..., logger_provider=... [only kwargs pydantic-ai accepts], **user kwargs)`; `obj is None` -> `Agent.instrument_all(settings)`; an `Agent` -> `obj.instrument = settings`; a `Model` -> returns `InstrumentedModel(obj, settings)`. `Agent.instrument_all` just sets `Agent._instrument_default = instrument` (class-wide default, read at run time as `self._instrument if self._instrument is not None else self._instrument_default`). Source: `SP/logfire/_internal/integrations/pydantic_ai.py:14-65`; `SP/pydantic_ai/agent/__init__.py:486, 1119-1130, 2967`.
- Ordering: the tracer provider handed over is the `ProxyTracerProvider` object that exists before `configure()` and is re-pointed by it, so calling `instrument_pydantic_ai()` first does not break wiring; but spans created before `configure()` trigger `LogfireNotConfiguredWarning`, and the docs-style order is `configure()` then `instrument_pydantic_ai()`. Source: `SP/logfire/_internal/config.py:1561-1569, 1638-1646`; `SP/logfire/_internal/tracer.py:54-69`.
- Probe: after `logfire.instrument_pydantic_ai()`, `type(Agent._instrument_default).__name__ == 'InstrumentationSettings'`. Run locally 2026-09-05.

### C2. Spans from `Agent(TestModel(), name='probe_agent').run_sync('hello')`

- Probe setup: `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False`; `logfire.configure(send_to_logfire='if-token-present', token=None, console=False, metrics=False, additional_span_processors=[SimpleSpanProcessor(MemoryExporter())])`; `logfire.instrument_pydantic_ai()`. Output `'success (no tool calls)'`. Two spans, one trace (`distinct trace ids: 1`), both `instrumentation_scope.name == 'pydantic-ai'`, both `status UNSET`:
  - `invoke_agent probe_agent` (root, `parent: null`). Attribute keys: `agent_name`, `final_result`, `gen_ai.agent.call.id`, `gen_ai.agent.name`, `gen_ai.aggregated_usage.input_tokens`, `gen_ai.aggregated_usage.output_tokens`, `gen_ai.conversation.id`, `gen_ai.operation.name` (`'invoke_agent'`), `logfire.json_schema`, `logfire.metrics`, `logfire.msg` (`'probe_agent run'`), `logfire.span_type` (`'span'`), `model_name`, `pydantic_ai.all_messages` (JSON string of the messages). Both `agent_name` and `gen_ai.agent.name` equal `'probe_agent'`.
  - `chat test` (child; `parent` == the agent span's `span_id`). Attribute keys: `gen_ai.agent.call.id`, `gen_ai.agent.name` (`'probe_agent'`, propagated via baggage), `gen_ai.conversation.id`, `gen_ai.input.messages`, `gen_ai.operation.name` (`'chat'`), `gen_ai.output.messages`, `gen_ai.provider.name` (`'test'`), `gen_ai.request.model` (`'test'`), `gen_ai.response.model`, `gen_ai.system` (`'test'`), `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `logfire.json_schema`, `logfire.msg` (`'chat test'`), `logfire.span_type`, `model_request_parameters`.
  Run locally 2026-09-05 (`scratchpad/probe_logfire_ai.py`).
- Source of the agent span: `span_attributes = {'model_name': ..., 'agent_name': agent_name, 'gen_ai.agent.name': agent_name, 'gen_ai.agent.call.id': ctx.run_id or '', 'gen_ai.conversation.id': ..., 'gen_ai.operation.name': 'invoke_agent', 'logfire.msg': f'{agent_name} run'}` then `settings.tracer.start_as_current_span(names.get_agent_run_span_name(agent_name), attributes=span_attributes)`; `final_result` is set only `if settings.include_content and span.is_recording()`. Source: `SP/pydantic_ai/capabilities/instrumentation.py:195-225`.
- Naming by instrumentation version: `InstrumentationNames.for_version(2)` -> `agent_run_span_name='agent run'`, `agent_name_attr='agent_name'`; any other version -> `'invoke_agent'` (formatted as `f'invoke_agent {agent_name}'`) and `'gen_ai.agent.name'`. `DEFAULT_INSTRUMENTATION_VERSION = 5`. So `agent run` is the legacy name; filter on `gen_ai.operation.name == 'invoke_agent'` or `name.startswith('invoke_agent ')` rather than on `'agent run'`. Source: `SP/pydantic_ai/_instrumentation.py:33, 693-756`.
- Model request span: attributes start from `{'gen_ai.operation.name': 'chat'}`; observed name `'chat test'` (operation + model name). Source: `SP/pydantic_ai/_instrumentation.py:320`; probe output above.
- Note for the SDK span used by pydantic-ai (`start_as_current_span`): the OTel SDK `Span.__exit__` records the exception and sets `StatusCode.ERROR` with `f"{type(exc_val).__name__}: {exc_val}"` when an exception escapes, except that pydantic-ai v5 deliberately leaves deferral exceptions `UNSET`. Source: `SP/opentelemetry/sdk/trace/__init__.py:1040-1061`; `SP/pydantic_ai/models/instrumented.py:129-131`.

### C3. `InstrumentationSettings.include_content`

- `InstrumentationSettings.__init__(*, tracer_provider=None, meter_provider=None, include_binary_content: bool = True, include_content: bool = True, include_model_request_parameters: bool = True, version: Literal[2, 3, 4, 5, 6] = DEFAULT_INSTRUMENTATION_VERSION, use_aggregated_usage_attribute_names: bool = True)`; `include_content`: "Whether to include prompts, completions, and tool call arguments and responses in the instrumentation events." Default `True`. Source: `SP/pydantic_ai/models/instrumented.py:82-91, 108-109, 151`.

## D. pydantic 2.13.5

### D1. `ConfigDict(frozen=True, extra='forbid')`

- Probe: assigning `m.a = 2` raises `pydantic_core.ValidationError` with error type `frozen_instance`; constructing with an unknown field `zzz=1` raises `ValidationError` with `[('extra_forbidden', ('zzz',))]`. Run locally 2026-09-05 (`scratchpad/probe_pydantic.py`).

### D2. `Decimal` and timezone-aware `datetime` round trips

- `model_dump_json()` of `cost: Decimal = Decimal('5')` -> `"cost":"5"` (JSON string); `Decimal('12.3456789012345678901234567890')` -> string with all digits preserved; `model_validate_json` round-trips to equal models with identical `Decimal` values. `model_dump()` (python mode) keeps `Decimal` objects. Caveat: a JSON *number* `5.10` validates to `Decimal('5.1')` (goes through float), whereas the string `"5.10"` yields `Decimal('5.10')`; so always emit/accept Decimals as strings (the default). Run locally 2026-09-05.
- `when: datetime` with `tzinfo=UTC` -> `"2026-09-05T12:00:00Z"`, with `+02:00` -> `"2026-09-05T12:00:00+02:00"`; round trip gives `TzInfo(0)` / `TzInfo(7200)` with the correct `utcoffset()` and models compare equal. A plain `datetime` annotation also accepts naive datetimes (`datetime(2026, 1, 1)` passed through unchanged); use `pydantic.AwareDatetime` if awareness must be enforced. Run locally 2026-09-05.

### D3. Constraints pydantic-ai 2.40 places on `output_type` models

- `ObjectOutputProcessor.__init__`: if `_utils.is_model_like(output)` (a `BaseModel` subclass, dataclass, `TypedDict`, or a type with `__is_model_like__`), it is used directly as `TypeAdapter(output)`; any other type is wrapped in a generated `response` TypedDict. The JSON schema is produced with `TypeAdapter.json_schema(schema_generator=GenerateToolJsonSchema)` and validated by `_utils.check_object_json_schema` (must be an object schema). Nothing inspects `frozen`/`extra`, and instances are produced by validation, so `ConfigDict(frozen=True, extra='forbid')` models are fine. Source: `SP/pydantic_ai/_output.py:855-921`; `SP/pydantic_ai/_utils.py:207-222`.
- Spec-level `UserError`s: "At least one output type must be provided other than `None`.", "`NativeOutput` must be the only output type.", "`PromptedOutput` must be the only output type.", "Only one `str` or `TextOutput` is allowed.", "At least one output type must be provided." Source: `SP/pydantic_ai/_output.py:466-607`.

## Recommended shapes

```python
# settings.py (pydantic-settings 2.15.0)
from decimal import Decimal
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        extra="ignore",          # unknown keys in the .env are not our business (default 'forbid' -> ValidationError)
        env_ignore_empty=True,   # `LOGFIRE_TOKEN=` behaves like "unset" -> default None; blank ints/Decimals -> defaults too
        # env_file intentionally unset: callers pass Settings(_env_file=path); nothing is read from CWD otherwise.
    )
    openrouter_api_key: str | None = None
    logfire_token: str | None = None
    ra_max_iterations: int = 3
    ra_budget_usd: Decimal = Decimal("1")


settings = Settings(_env_file=some_path)   # or Settings(_env_file=None) to read only os.environ
```

```python
# tracing.py (logfire 5.0.0 + opentelemetry-sdk 1.44.0)
import json
from collections.abc import Sequence
from pathlib import Path

import logfire
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import format_span_id, format_trace_id


class JsonlSpanExporter(SpanExporter):
    def __init__(self, path: Path) -> None:
        self._path = path

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        with self._path.open("a", encoding="utf-8") as fh:
            for span in spans:
                attrs = dict(span.attributes or {})
                if attrs.get("logfire.span_type") == "pending_span":   # never arrives in 5.0.0, cheap to guard
                    continue
                fh.write(json.dumps({
                    "trace_id": format_trace_id(span.context.trace_id),
                    "span_id": format_span_id(span.context.span_id),
                    "parent_span_id": format_span_id(span.parent.span_id) if span.parent else None,
                    "name": span.name,
                    "start_time_ns": span.start_time,
                    "end_time_ns": span.end_time,
                    "status": span.status.status_code.name,          # UNSET / OK / ERROR
                    "status_description": span.status.description,
                    "attributes": attrs,                             # values are str/int/float/bool/tuple; complex ones already JSON strings
                }, default=str) + "\n")
        return SpanExportResult.SUCCESS


logfire.configure(
    send_to_logfire="if-token-present",   # with token=None and no LOGFIRE_TOKEN: no network, no .logfire/, no warning
    token=None,
    console=False,                        # or logfire.ConsoleOptions(...) to switch it on
    metrics=False,
    service_name="recursive-application",
    additional_span_processors=[SimpleSpanProcessor(JsonlSpanExporter(path))],   # synchronous: file complete at span end
    # scrubbing=False if attribute names like `openrouter_api_key` must not arrive as "[Scrubbed due to 'api_key']"
)
logfire.instrument_pydantic_ai()          # Agent.instrument_all(InstrumentationSettings(tracer_provider=<logfire proxy>))
```

Test-suite notes: `pydantic_ai.models.ALLOW_MODEL_REQUESTS = False` in `conftest.py`; ensure `LOGFIRE_TOKEN` is unset (`monkeypatch.delenv('LOGFIRE_TOKEN', raising=False)`) and pass `send_to_logfire=False` in tests; a second `logfire.configure(...)` per test is allowed and replaces the previous processors without warnings; `configure(local=True)` gives an isolated `Logfire` instance whose `.span()` and `.instrument_pydantic_ai()` bypass the global default.
