# Development Guide

This guide is for people who want to develop, modify or contribute to `tvh-radio`.

For installing and operating an existing system, see [Installation](installation.md) and [Operation](operation.md).

## Project structure

The main parts of the repository are:

```text
tvh-radio/
├── master.py
├── streamer.py
├── config.json
├── channels/
├── images/
├── examples/
├── docs/
├── iheart_extract/
├── systemd/
├── requirements.txt
└── README.md
```

The most important application components are `master.py` and `streamer.py`.

### `master.py`

The master process is responsible for orchestration.

It:

- Loads the master configuration.
- Loads and validates channel configurations.
- Allocates and manages UDP ports.
- Generates the channel playlist.
- Starts one streamer process per channel.
- Monitors streamer processes.
- Restarts failed streamers.
- Applies restart limits and backoff.
- Shuts down streamers cleanly.

The master should remain focused on process management and orchestration.

### `streamer.py`

The streamer process is responsible for one radio channel.

It handles:

- Radio audio input.
- Metadata retrieval.
- Artwork and station logos.
- Now-playing image generation.
- GStreamer pipeline management.
- H.264 video encoding.
- AAC audio encoding.
- MPEG-TS output.
- Audio recovery.
- Graceful shutdown.

Channel-specific streaming behaviour belongs here rather than in `master.py`.

## Development environment

A development environment should use the same basic dependencies as a normal installation.

Create a virtual environment with access to the system-installed GStreamer/PyGObject packages:

```bash
python3 -m venv .venv --system-site-packages
```

Activate it:

```bash
source .venv/bin/activate
```

Install the Python dependencies:

```bash
pip install -r requirements-dev.txt
```

The requirements-dev.txt file installs the application's Python dependencies along with pytest. Use requirements.txt instead when installing the application without the development tools. PyGObject and GStreamer remain system-provided dependencies.

PyGObject is intentionally not installed from the root `requirements.txt`. The project expects the operating system's GObject Introspection/PyGObject and GStreamer packages to provide it.

For the iHeart extractor, use its separate requirements file:

```bash
cd iheart_extract
pip install -r requirements.txt
```

See [Installation](installation.md) for the system dependencies required by the project.

## Running during development

The master can be run directly during development:

```bash
python master.py
```

This starts the configured channel streamers and keeps the master in the foreground.

Stop it with:

```text
Ctrl+C
```

For development work, running the master directly is often more convenient than using systemd because application output is immediately visible.

## Configuration validation

Before running after a configuration change, use:

```bash
python master.py --validate
```

Validation checks the master and channel configuration without starting streamer processes.

It is useful during development because configuration mistakes can be found before the GStreamer pipelines and network streams are started.

When adding or changing configuration fields, update the validation logic in `master.py` at the same time.

## Architecture and responsibility boundaries

The project intentionally separates orchestration from streaming.

```text
                 master.py
                    |
       +------------+------------+
       |            |            |
       v            v            v
 streamer.py  streamer.py  streamer.py
   channel A    channel B    channel C
```

When adding functionality, consider which level owns the responsibility.

### Functionality that belongs in the master

Examples include:

- Discovering channel configuration files.
- Validating configuration.
- Allocating UDP ports.
- Generating the playlist.
- Starting and stopping streamers.
- Monitoring child processes.
- Restarting failed streamers.
- Restart-loop detection.
- Backoff handling.

### Functionality that belongs in a streamer

Examples include:

- Metadata polling.
- Artwork handling.
- Image generation.
- Icecast/audio handling.
- GStreamer pipeline operation.
- MPEG-TS generation.
- Channel-specific recovery.

Avoid moving GStreamer or channel-specific streaming logic into the master simply because the master already has access to the channel configuration.

Keeping this boundary clear makes the system easier to understand and reduces the risk that a problem in one channel affects the process manager.

## Logging

Structured application logging is part of the core application rather than an optional feature.

When adding new functionality, provide useful log messages for:

- Startup.
- Shutdown.
- Configuration problems.
- External service failures.
- Recovery attempts.
- Successful recovery.
- State changes.
- Unexpected process termination.

Logs should help an operator understand what happened without requiring a debugger.

Avoid logging the same transient error continuously when a state-based message can communicate the situation more clearly.

For example, a service that is temporarily unavailable should not necessarily generate an identical error message every few seconds if the application can record the transition into an error state and the eventual recovery.

## Error handling and resilience

`tvh-radio` is intended to operate continuously, so external failures should generally be treated as recoverable where practical.

Examples include:

- Metadata APIs becoming unavailable.
- Metadata APIs returning HTTP 204.
- Invalid or incomplete metadata.
- Album artwork becoming unavailable.
- Station logo downloads failing.
- Temporary Icecast failures.

When changing error handling:

1. Identify whether the failure is transient or permanent.
2. Preserve useful existing state where appropriate.
3. Use configured fallback behaviour.
4. Retry where the existing architecture expects recovery.
5. Log the transition and eventual recovery.
6. Avoid allowing one external failure to terminate an otherwise healthy channel.

Do not hide unexpected programming errors behind broad exception handlers.

## Graceful shutdown

Graceful shutdown is part of the core application behaviour.

Changes to long-running components should consider what happens when the process receives a shutdown request.

In particular, changes involving GStreamer pipelines, network connections or worker threads should ensure that resources can be released without leaving the process or pipeline running indefinitely.

Test both normal startup and normal shutdown after making changes to lifecycle-related code.

## Automated testing

`tvh-radio` uses [pytest](https://docs.pytest.org/) for automated tests. The test suite covers configuration validation, UDP allocation, playlist generation, metadata handling and master process management.

Automated tests should be the first check after a code change. They provide fast feedback and do not require a running TVHeadend instance or access to live radio streams.

### Installing test dependencies

From the repository root, create and activate a development virtual environment if one is not already available:

```bash
python3 -m venv .venv --system-site-packages
source .venv/bin/activate
```

Install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

The development requirements include pytest and the application's normal Python dependencies.

The `--system-site-packages` option allows the virtual environment to access the system-installed PyGObject and GStreamer Python bindings where available.

### Running the test suite

Run all automated tests from the repository root:

```bash
python -m pytest -q
```

For more detailed output:

```bash
python -m pytest -v
```

Run an individual test module:

```bash
python -m pytest -q tests/test_process_management.py
```

Run a specific test:

```bash
python -m pytest -q tests/test_process_management.py::test_restart_loop_without_failures
```

During development, prefer running the relevant tests after each small change. Run the complete suite before committing significant changes.

### Test organisation

The tests are stored in the `tests/` directory.

| Test module | Main coverage |
|---|---|
| `test_master_config.py` | Master configuration validation |
| `test_channel_config.py` | Channel configuration validation |
| `test_config_loading.py` | Configuration discovery and loading |
| `test_udp.py` | UDP allocation and port handling |
| `test_playlist.py` | Playlist generation and file management |
| `test_metadata.py` | Metadata retrieval, mapping, fallback and recovery state |
| `test_process_management.py` | Streamer startup, monitoring, restart policy, backoff and shutdown |
| `conftest.py` | Shared pytest fixtures |

The suite is intentionally structured around application responsibilities rather than individual implementation details.

### Testing external dependencies

Tests should not depend on live internet radio stations, metadata services, or real streamer subprocesses unless an integration test explicitly requires them.

Use pytest fixtures and `monkeypatch` to simulate external behaviour. Examples include:

- Mocking HTTP responses and network exceptions for metadata handling.
- Replacing `time.monotonic()` to test restart and backoff boundaries without waiting.
- Replacing `time.sleep()` to control the master monitoring loop.
- Using fake subprocess objects to test process-management decisions without launching streamers.
- Using temporary directories for configuration and playlist file operations.

Tests involving time should be deterministic. Avoid real delays where a simulated clock can provide the same coverage.

### Linting and syntax checks

The project includes Ruff configuration in `pyproject.toml`.

If Ruff is installed, run:

```bash
ruff check .
```

Python files can also be checked for syntax errors using:

```bash
python -m compileall -q master.py streamer.py metadata.py tests
```

Linting and compilation are additional checks; neither replaces the automated tests.

### Manual and integration testing

The automated test suite does not replace manual streaming checks.

Changes involving GStreamer pipelines, audio-source recovery, video generation, MPEG-TS muxing or UDP delivery should be tested against a working channel configuration.

Relevant checks include:

- Confirming that the channel produces playable video and audio.
- Verifying that metadata and artwork updates appear correctly.
- Checking recovery following temporary service interruptions.
- Confirming that the streamer and master shut down correctly.
- Testing multiple simultaneous channels when changing master process management.
- Confirming TVHeadend integration when applicable.

Use the manual testing and regression-testing sections below for additional guidance.

Live-service failures can be difficult to reproduce reliably. Where practical, use controlled test endpoints rather than deliberately disrupting production services.

### Adding or modifying tests

When introducing a feature or fixing a bug:

1. Add or update tests covering the expected behaviour.
2. Include important boundary conditions and failure scenarios.
3. Mock external services and processes where practical.
4. Run the affected test module.
5. Run the complete test suite.
6. Run linting checks where available.
7. Perform manual integration testing if the change affects streaming or process lifecycle behaviour.

Keep tests independent so that execution order does not affect their results.

When fixing a regression, prefer a test that would fail against the original bug and pass with the corrected implementation.

### Before committing

The minimum automated checks for code changes are:

```bash
python -m pytest -q
```

Where Ruff is installed, also run:

```bash
ruff check .
```

Review the working tree before committing:

```bash
git status
git diff
```

Automated tests establish confidence in the covered behaviour, but passing tests do not guarantee that live GStreamer pipelines or external services will work correctly.

## Manual Testing changes

Testing should be performed incrementally.

A useful basic sequence is:

### 1. Validate configuration

```bash
python master.py --validate
```

### 2. Run the application manually

```bash
python master.py
```

Watch the output for startup errors.

### 3. Test the generated stream

Use a media player such as `mpv` against the channel's UDP endpoint:

```bash
mpv udp://127.0.0.1:1234
```

Replace the address and port with the channel being tested.

This allows the streamer to be tested independently of TVHeadend.

### 4. Test recovery behaviour

When changing resilience or process-management code, test relevant failure conditions deliberately.

Examples include:

- Streamer process termination.
- Repeated streamer failures.
- Restart limit handling.
- Restart backoff.
- Audio source interruption.
- Metadata API failure.
- Metadata HTTP 204 responses.
- Missing artwork.

Only test destructive failure scenarios in a development or otherwise controlled environment.

### 5. Test multiple channels

Changes to `master.py` should be tested with more than one channel where practical.

A failure in one streamer should not unintentionally affect the other channels.

## Regression testing

Before considering a significant change complete, run the automated test suite and manually verify the affected functionality. Manual regression testing remains particularly important for live streaming, GStreamer pipeline behaviour and integration with external services.

The core regression areas are:

- Configuration validation.
- Master startup.
- Multiple channel startup.
- Metadata updates.
- Artwork handling.
- Audio streaming.
- Video generation.
- MPEG-TS output.
- UDP delivery.
- Streamer restart behaviour.
- Restart backoff.
- Graceful shutdown.
- Playlist generation.
- TVHeadend integration where applicable.

Not every change requires every test, but changes to the master process or streamer lifecycle should receive broader testing because they affect the overall system.

## Testing with systemd

The development workflow can use direct execution for fast iteration, while systemd should also be tested before a release when the change affects service operation.

Useful commands include:

```bash
sudo systemctl restart tvh-radio
sudo systemctl status tvh-radio
journalctl -u tvh-radio -f
```

When testing service lifecycle changes, verify both startup and graceful shutdown.

## Working with channel configurations

Channel configurations are JSON files under:

```text
channels/
```

Example configurations are provided under:

```text
examples/channels/
```

When creating a development/test channel, use a separate channel configuration rather than changing a working channel unnecessarily.

Validate the configuration before starting the master:

```bash
python master.py --validate
```

Remember that automatically allocated UDP ports may be persisted by normal master startup. The validation command itself does not start streamers or modify configurations.

## Making changes safely

When modifying the project:

1. Understand which component owns the behaviour.
2. Make the smallest reasonable change.
3. Run configuration validation.
4. Run the affected component.
5. Test the normal path.
6. Test relevant failure/recovery paths.
7. Check the logs.
8. Test other channels when the change affects shared infrastructure.
9. Review the resulting diff before committing.

Avoid combining unrelated changes into one commit where possible.

Small, focused commits make it easier to understand and troubleshoot the project history.

## Git and GitHub workflow

Development work is tracked in Git and GitHub.

Issues are used to define development work and milestones group related work toward releases.

A typical workflow is:

```text
Issue
  |
  v
Development
  |
  v
Testing
  |
  v
Commit
  |
  v
Pull request / review
  |
  v
Merge
```

Use the project's existing issue and milestone structure when adding new work.

Before committing:

```bash
git status
git diff
```

Review the changes and make sure temporary files, generated output, credentials and local development files are not being committed.

The repository's `.gitignore` should be used for local development artefacts.

## Adding new configuration options

When adding a configuration option, update all relevant places rather than only the code that consumes it.

Consider:

- Configuration loading.
- Configuration validation.
- Default/example configuration.
- Channel examples if applicable.
- Documentation.
- Error messages.
- Tests or manual regression checks.

A configuration option is not complete until an operator can understand what it does and how to configure it.

## Adding new channel fields

When adding a channel configuration field:

1. Define how the streamer uses it.
2. Add validation where appropriate.
3. Add it to the example configuration if it is part of the supported configuration.
4. Document it in [Channels](channels.md).
5. Consider fallback/default behaviour.
6. Test both valid and invalid values.

## GStreamer development

GStreamer is a central part of the streamer.

The pipeline combines the generated video with the radio audio and produces an MPEG-TS stream for UDP output.

When modifying the pipeline, test:

- Video negotiation.
- Audio negotiation.
- H.264 encoding.
- AAC encoding.
- MPEG-TS muxing.
- UDP output.
- Pipeline shutdown.

GStreamer errors such as `not-negotiated` can indicate that elements cannot agree on compatible media formats. Preserve the relevant GStreamer error and debug information when diagnosing pipeline changes.

Test pipeline changes independently with a direct UDP/media-player check before involving TVHeadend.

## External services

The application depends on external services for some channel functionality.

These can include:

- Radio streams.
- Metadata APIs.
- Station logo URLs.
- Album artwork URLs.

Development changes should account for the fact that these services can fail or change independently of the application.

Do not make successful operation depend on every external service being available at all times when an existing fallback or recovery mechanism is available.

## Documentation

Documentation is part of the implementation.

When behaviour changes, review the relevant documentation:

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Channels](channels.md)
- [Operation](operation.md)
- [Troubleshooting](troubleshooting.md)
- [TVHeadend Integration](tvheadend.md)

Update examples when configuration syntax changes.

Keep documentation focused on what an operator or developer actually needs to know rather than documenting internal implementation details that are likely to change.

## Before a release

Before preparing a release:

- Run the complete automated test suite.
- Run Ruff lint checks.
- Run configuration validation.
- Perform a clean installation test.
- Test multiple channels.
- Verify audio and video.
- Verify metadata and artwork.
- Test audio recovery.
- Test streamer restart behaviour.
- Test restart backoff.
- Test graceful shutdown.
- Test systemd operation.
- Verify playlist generation.
- Verify TVHeadend integration.
- Review documentation.
- Review example configurations.
- Review the repository for unintended files or changes.
- Review the Git history and release changes.

The release checklist in the relevant GitHub issue should be used as the authoritative list of release-specific work.

## Related documentation

- [Installation](installation.md)
- [Configuration](configuration.md)
- [Channels](channels.md)
- [Operation](operation.md)
- [Troubleshooting](troubleshooting.md)
- [TVHeadend Integration](tvheadend.md)
