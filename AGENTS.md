# Development Guidelines

## Project

This project is a Python/GStreamer-based radio-to-IPTV
streaming application designed primarily for TVHeadend.

## Development principles

- Preserve working functionality unless deliberately changing it.
- Make changes incrementally.
- Test each significant change before proceeding.
- Prefer simple, maintainable solutions.
- Do not introduce unnecessary abstractions prematurely.

## Python

The project author is comfortable with PHP and JavaScript
but is still learning Python.

Code should therefore:
- favour readability over cleverness
- include useful comments where appropriate
- avoid unnecessarily complex Python constructs

## GStreamer

The pipeline must remain suitable for 24x7 operation.

Important:
- graceful shutdown is required
- useful logging is required
- audio recovery must not unnecessarily kill video
- avoid per-frame logging

## Git

- Make small, meaningful commits.
- Do not commit secrets.
- Do not commit generated runtime files.
- Preserve known-good milestones with tags.

## Architecture

One streamer process represents one channel.

The master process:
- manages channel processes
- manages the UDP port pool
- generates the M3U playlist
- handles process supervision
- eventually handles demand-based startup/shutdown