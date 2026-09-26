# LiftLine

> **AI-powered elevator service dispatch with intelligent routing, voice intake, and automated technician assignment**

LiftLine is a production-ready phone intake and dispatch system for elevator maintenance. It combines type-safe AI routing, voice interaction, and multi-channel notifications to automate the entire service request workflow—from safety triage to technician dispatch.

## 🎯 Key Features

- **Safety-First Triage** — Immediate dispatcher routing for entrapment, injury, or danger keywords
- **Type-Safe AI Routing** — TypeSafe Jev makes confident, auditable decisions on data source selection
- **Voice & Keypad Interface** — Natural speech recognition with fallback to DTMF input
- **Multi-System Integration** — Unified access to CRM, SAP, IoT telemetry, and field service data
- **Automated Dispatch** — Intelligent technician matching based on certification, availability, and location
- **Warranty & Coverage** — Real-time validation of service agreements and billable callout approval
- **Durable Notifications** — Retry-safe outbox with iMessage delivery via Photon Spectrum
- **Security Hardened** — PIN verification, signed webhooks, redacted logs, and protected APIs

## 🚀 Quick Start

```sh
# Run the interactive demo (no external services required)
python3 -m lift_agent demo

# Try different scenarios
python3 -m lift_agent demo --scenario entrapment
python3 -m lift_agent demo --scenario billable
python3 -m lift_agent demo --scenario clean
python3 -m lift_agent demo --scenario unauthorized

# Use live TypeSafe Jev routing (requires TYPESAFE_API_KEY)
python3 -m lift_agent demo --live-jev
```

Each demo run creates isolated SQLite databases, simulates the complete conversation flow, and prints a detailed routing trace. No real notifications are sent in demo mode.

## 🛠️ Tech Stack

### Core Infrastructure

- **Python 3.11+** — Backend service using only standard library (no external dependencies)
- **SQLite** — Embedded databases for CRM, SAP, IoT telemetry, and field service data
- **Node.js 22+** — Photon bridge service for iMessage notifications

### AI & Intelligence

- **[TypeSafe Jev](https://docs.typesafe.ai/api)** — Type-safe AI routing with confidence scoring and probability distributions
  - Structured Choice decisions (not conversational LLM)
  - 80%+ confidence threshold enforcement
  - Auditable routing trace with model version tracking
- **ElevenLabs** — Natural text-to-speech for voice responses (optional)

### Voice & Telephony

- **[Twilio Voice](https://www.twilio.com/docs/voice)** — Phone intake with TwiML state machine
  - Speech recognition with DTMF fallback
  - Webhook-driven conversation flow
  - Request signature validation for security

### Notifications

- **[Photon Spectrum](https://photon.codes/docs/spectrum-ts)** — iMessage delivery via `spectrum-ts` (v12.10.1)
  - Durable outbox pattern with retry logic
  - Consent-based messaging
  - Delivery status tracking

### Security & Reliability

- **PIN Hashing** — SHA-256 contact verification
- **Webhook Signatures** — Twilio request validation
- **Protected APIs** — Bearer token authentication for operator endpoints
- **Redacted Logging** — PII scrubbing in audit trails
- **Idempotent Webhooks** — Retry-safe state transitions

## 📋 How It Works

1. **Safety Triage** — Immediate dispatcher routing for entrapment, injury, or danger keywords
2. **Identity Verification** — Phone number matching + 6-digit PIN validation
3. **AI Routing** — Jev selects optimal data sources for 7 workflow questions across 4 systems
4. **Equipment Lookup** — Site-scoped machine resolution with telemetry freshness checks
5. **Fault Analysis** — Component correlation, follow-up event tracking, prior repair matching
6. **Coverage Validation** — Warranty evaluation, maintenance contract checks, billable approval
7. **Technician Dispatch** — Certification matching, availability checks, travel time estimation
8. **Notification Delivery** — Consent-based case reports and ETA updates via iMessage
9. **Dispatcher Confirmation** — Acceptance endpoint with final ETA and assignment lock-in

The voice experience is a **structured workflow**, not an open-ended chatbot. Jev makes typed routing decisions; all business logic remains deterministic and auditable.

## 📁 Project Structure

```
lift_agent/
├── voice.py           # TwiML state machine & conversation flow
├── router.py          # TypeSafe Jev integration & routing logic
├── service.py         # Business logic: investigation, dispatch, coverage
├── store.py           # Database schemas & synthetic fixtures
├── server.py          # Twilio webhooks & operator APIs
└── notifications.py   # Durable outbox worker

integrations/photon/
└── server.mjs         # Photon Spectrum iMessage bridge

docs/
└── operations.md      # Production deployment guide

seed/                  # Synthetic data fixtures
tests/                 # Unit & integration tests
```

### CLI Commands

```sh
# Create persistent synthetic data
python3 -m lift_agent seed

# View cases, work orders, and routing traces
python3 -m lift_agent report

# Start production server (requires .env configuration)
python3 -m lift_agent serve

# Process notification outbox manually
python3 -m lift_agent notify
```

## 🚀 Production Deployment

### Environment Setup

Copy `.env.example` to `.env` and configure:

```sh
# Required for live operation
TWILIO_AUTH_TOKEN=your_token
TWILIO_PHONE_NUMBER=+1234567890
DISPATCHER_PHONE=+1234567890
PUBLIC_BASE_URL=https://your-domain.com
TYPESAFE_API_KEY=your_key

# Photon iMessage (optional but recommended)
SPECTRUM_PROJECT_ID=your_project_id
SPECTRUM_PROJECT_SECRET=your_secret
PHOTON_BRIDGE_TOKEN=your_token

# Enable notifications in production
MODE=live
SEND_NOTIFICATIONS=true
```

### Start Services

```sh
# Backend server (port 8080)
python3 -m lift_agent serve

# Photon bridge (port 8081, optional)
cd integrations/photon
npm ci
npm start
```

### Twilio Configuration

Set incoming call webhook to:

```
POST https://your-domain.com/voice
```

See `docs/operations.md` for dispatcher acceptance endpoints, deployment limits, and production considerations.

## ✅ Testing

```sh
# Run full test suite
python3 -m unittest discover -s tests -v
```

**Test Coverage:**

- ✅ Primary happy path (warranty-covered repair)
- ✅ Entrapment scenario (immediate dispatcher routing)
- ✅ Billable callout (explicit approval flow)
- ✅ Clean resolution (no prior faults)
- ✅ Unauthorized caller (PIN mismatch)
- ✅ Stale telemetry detection
- ✅ Duplicate case prevention
- ✅ Webhook signature validation
- ✅ Retry-safe state transitions
- ✅ Consent-based notifications
- ✅ Jev routing failures

## 🎬 Demo Scenarios

Each scenario demonstrates different workflow paths:

| Scenario         | Description                                             |
| ---------------- | ------------------------------------------------------- |
| **Default**      | Warranty-covered repair with prior component fault      |
| **Entrapment**   | Safety keyword triggers immediate dispatcher routing    |
| **Billable**     | Out-of-warranty repair requiring explicit cost approval |
| **Clean**        | No prior faults; technician dispatched for new issue    |
| **Unauthorized** | PIN mismatch blocks automated processing                |

Demo data includes:

- **Machine 1002** (Car B) with door lock circuit faults
- **Priya** (authorized contact): `+15550100100`, PIN `246810`
- **Ravi** (certified technician) with 20-minute travel time
- Prior repair on **September 7, 2026** for the same component

## 🏗️ Architecture Highlights

### Type-Safe AI Routing

- Jev answers 7 workflow questions by selecting from 7 data sources
- 80%+ confidence threshold with probability distribution validation
- Expected answer allowlist prevents hallucinated sources
- Full routing trace with model version and confidence scores

### Durable Notification Pattern

- Atomic outbox writes with case/work-order creation
- Retry logic with exponential backoff
- Delivery status tracking (pending → sent → delivered → failed)
- Consent verification before sending

### Security Layers

1. **Twilio signature validation** — Prevents webhook spoofing
2. **PIN hashing (SHA-256)** — Contact verification without plaintext storage
3. **Bearer token auth** — Protected operator APIs
4. **PII redaction** — Logs scrub phone numbers and PINs
5. **HTTPS enforcement** — Production requires TLS

### Zero External Dependencies

The Python backend uses **only the standard library**:

- `http.server` for webhooks
- `sqlite3` for data persistence
- `urllib.request` for Jev API calls
- `hashlib` for PIN verification
- `hmac` for signature validation

No pip packages required for core functionality.

## 📚 Integration References

- **[TypeSafe Jev API](https://docs.typesafe.ai/api)** — Typed choices with calibrated confidence
- **[Twilio Voice](https://www.twilio.com/docs/voice/twiml/gather)** — Speech/keypad collection
- **[Twilio Security](https://www.twilio.com/docs/usage/security)** — Request signature validation
- **[Photon Spectrum](https://photon.codes/docs/spectrum-ts/getting-started)** — iMessage delivery
- **[ElevenLabs](https://elevenlabs.io/docs)** — Text-to-speech synthesis

---

**Built for the TypeSafe AI Hackathon** • September 26, 2026
