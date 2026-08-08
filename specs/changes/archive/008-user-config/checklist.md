# 008-user-config checklist

## Specification quality

- [x] Specification approved <!-- sdd:approval -->
- [x] Goals, non-goals, compatibility, risks, and rollback are explicit.
- [x] Every requirement has an observable acceptance scenario.

## Verification evidence

- [x] AC1 pytest: ``tests/test_config.py::test_project_dotenv_overrides_user_dotenv`` and ``tests/test_config.py::test_process_environment_overrides_both_dotenv_files``
- [x] AC1 trace: configuration source metadata and selected ``api_key_source`` are asserted by the configuration tests.
- [x] AC2 pytest: ``tests/test_config.py::test_missing_user_dotenv_preserves_project_and_default_behavior``, ``tests/test_config.py::test_empty_user_dotenv_is_ignored``, and ``tests/test_config.py::test_unreadable_user_dotenv_is_ignored``
- [x] AC2 trace: the configuration source tuple is asserted as project-only when the user file is absent.
- [x] AC3 pytest: ``tests/test_config.py::test_runtime_emits_safe_config_loaded_trace``
- [x] AC3 trace: ``config_loaded`` contains safe metadata and excludes the test secret.
- [x] AC4 pytest: ``tests/test_config.py::test_initialize_user_env_is_private_and_only_supplements_existing_values``
- [x] AC4 trace: initializer verification is paired with the safe startup Trace assertion in AC3; no file contents are traced.
- [x] Tests and compile checks pass.
- [x] No credentials or generated runtime state are included.

## Completion

- [x] Capability updated: `specs/capabilities/runtime.md`
- [x] Ready to archive.
