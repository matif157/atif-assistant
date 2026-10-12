# Jarvis-Style Human+AI Hybrid Assistant - Complete Planning Document

Created: 2026-10-12
Status: Planning Phase

## Project Vision
Create a local-first, privacy-focused assistant that blends human understanding with AI. Goal: Jarvis-like capability but affordable, fully offline-capable, learning from real life.

## Core Requirements
- Local-first: run on own hardware without mandatory cloud
- Mode-free, evidence-backed (like atif-assistant)
- Integrates with Google Drive, Gmail, WhatsApp, local files
- Auto-extract tasks from conversations
- Glasses with mic/camera: voice recognition, tone, face ID, spatial mapping
- Location tracking, home mapping, object recognition/material understanding
- Can estimate physical capabilities vs objects
- Learn continuously, update memory/facts
- Emotionally aware (human-like)
- Phased: each phase standalone; missing phase doesn't break
- Progressive enhancement

## Current Context (from atif-assistant)
Repo: ~/Projects/atif-assistant (GitHub: matif157/atif-assistant)
Phases 1A-2 done; Phase 3 in progress (CRUD). 
Local tools: espeak-ng, whisper-cli, ollama (llama3.2:1b), sherpa-onnx speaker ID
Safety: evidence labels, advisory-only speaker ID, isolation tested (392/0)

## High-Level Architecture Ideas
- Core: evidence store + knowledge graph + memory (facts/episodes/rules/learned)
- Ingest: email, chat (WhatsApp exports), Drive, files, audio
- Perception: glasses sensors (audio/video), spatial/scene understanding
- Planning: task extraction, todo management
- Reasoning: context-aware, personal history
- Actuation/UI: voice, text, PWA
- Privacy: all local, encrypted at rest, no telemetry

## Phased Plan (proposed structure)
1. Foundation (extend atif-assistant core)
2. Connectors (Drive/Gmail/WhatsApp/local)
3. Task extraction & todo automation
4. Perception layer (glasses integration concept)
5. Spatial/home mapping & 3D
6. Human understanding/emotion modeling
7. Knowledge graph + reasoning
8. Optimization for local/offline
9. Hardware integration (glasses spec research)
10. Deployment/self-hosting

## Glasses Research Notes
Need affordable options: consider ESP32+camera, Raspberry Pi Zero 2W+display, or existing AR glasses? 
Need mic, camera, display, battery, connectivity to local system (WiFi/BLE/direct). 
Focus on practical affordable path.

## Data Management Strategy
- SQLite + FTS + vector store (local embeddings)
- Incremental indexing
- Deduplication
- Tiered storage (recent vs archive)
- Compressed evidence
- Avoid cloud; use local disks with pruning

## Implementation Notes
- Start from existing atif-assistant (solid base)
- Keep phases minimal & testable
- GitHub-first per AGENTS.md
- Tests must pass before commits
- Each change small, verifiable

## Next Actions
- Create detailed phase files in repo
- Add connectors framework
- Define data model extensions
- Research affordable glasses
- Design ingestion pipeline (read-only first, propose-then-approve)

This is planning only - do not merge into active work yet.
