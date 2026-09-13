# Sky — Eco-Travel Advisor Chatbot

An AI-powered chatbot that helps travelers plan sustainable trips by providing eco-friendly transport, accommodation, and activity recommendations with real-time carbon footprint calculations.

Built with **Rasa 3.6** (NLU + Core) and a custom HTML/CSS/JS frontend.

## Features

- **Eco-Friendly Trip Planning** — collects destination, dates, budget, number of travelers, and sustainability preferences through adaptive multi-turn dialogue
- **Carbon Footprint Calculator** — real-time CO₂ emissions via Climatiq API for each transport mode, with green/amber/red colour-coded cards
- **Smart Recommendations** — weighted eco-scoring function ranks options by carbon impact, price, and user preferences
- **7 Live APIs** — Climatiq (carbon), OpenRouteService (distance), Nominatim (geocoding), Overpass/OSM (hotels, transport, attractions), Wikipedia (city info), Open-Meteo (weather), Frankfurter (currency)
- **GPS Location Detection** — browser geolocation with Nominatim reverse geocoding
- **Interactive Intro Tour** — 12-step guided onboarding for new users
- **Human Advisor Escalation** — full context handover with animated modal UX
- **Multi-Conversation Sidebar** — rename, pin, delete trips; switch without losing context
- **Accessibility** — full ARIA attributes, keyboard navigation, screen-reader support
- **Privacy-First** — no cookies, no tracking, no persistent storage (InMemoryTrackerStore)

## Tech Stack

| Component | Technology |
|-----------|-----------|
| NLU & Dialogue | Rasa Open Source 3.6.21, rasa-sdk 3.6.2 |
| Language | Python 3.10 |
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Communication | Rasa SocketIO channel |
| Containerization | Docker + Docker Compose |
| Pipeline | WhitespaceTokenizer → RegexFeaturizer → LexicalSyntacticFeaturizer → CountVectorsFeaturizer (×2) → DIETClassifier (50 epochs) → FallbackClassifier (0.65) |

## Project Structure

```
ecoTravelAdvisor/
├── actions/
│   └── actions.py          # 19 custom actions (API calls, scoring, validation)
├── data/
│   ├── nlu.yml             # 27 intents, 3000+ training examples
│   ├── stories.yml         # 31 conversation stories
│   └── rules.yml           # 34 dialogue rules
├── frontend/
│   ├── index.html          # Chat UI with sidebar, modals, cards
│   ├── style.css           # Responsive styles, dark/light support
│   └── script.js           # SocketIO client, tour, GPS, carousels
├── tests/
│   ├── test_stories.yml    # 16 end-to-end test stories
│   └── test_actions.py     # 95 pytest unit tests
├── config.yml              # Rasa NLU + Core pipeline configuration
├── domain.yml              # Intents, entities, slots, responses, actions
├── credentials.yml         # Channel credentials (SocketIO)
├── endpoints.yml           # Action server endpoint
├── Dockerfile              # Rasa server container
├── Dockerfile.actions      # Action server container
├── docker-compose.yml      # 3-service orchestration
├── .env.example            # Template for API keys
└── .gitignore
```

## Quick Start

### Prerequisites

- Python 3.10
- pip

### 1. Clone and set up environment

```bash
git clone https://github.com/hanberkay0102/Sky-Eco-Travel-Advisor.git
cd ecoTravelAdvisor
python3.10 -m venv rasa-env
source rasa-env/bin/activate
pip install rasa==3.6.21 rasa-sdk==3.6.2
```

### 2. Configure API keys

```bash
cp .env.example .env
# Edit .env and add your real API keys
```

### 3. Train the model

```bash
rasa train
```

### 4. Run (3 terminals)

**Terminal 1 — Action Server:**
```bash
cd ecoTravelAdvisor && source rasa-env/bin/activate
rasa run actions
```

**Terminal 2 — Rasa Server:**
```bash
cd ecoTravelAdvisor && source rasa-env/bin/activate
rasa run --enable-api --cors "*"
```

**Terminal 3 — Frontend:**
```bash
cd ecoTravelAdvisor/frontend
python3 -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080) in your browser.

### Docker Alternative

```bash
docker-compose up --build
```

## Testing

```bash
# NLU cross-validation (5-fold)
rasa test nlu --nlu data/nlu.yml --cross-validation --folds 5

# Core story testing
rasa test core --stories tests/test_stories.yml

# Unit tests
pytest tests/test_actions.py -v
```

### Test Results

| Metric | Score |
|--------|-------|
| NLU Cross-Validation Accuracy | 77.7% (27 intents, 3016 examples) |
| NLU Entity F1 | 96.7% |
| Core Story Accuracy | 100% (16/16 stories) |
| Core Action Accuracy | 100% (53/53 actions) |
| Unit Tests | 95 tests passing |

## APIs Used

| API | Purpose | Key Required |
|-----|---------|:---:|
| [Climatiq](https://www.climatiq.io/) | Carbon emission calculations | Yes |
| [OpenRouteService](https://openrouteservice.org/) | Distance/routing between cities | Yes |
| [Nominatim](https://nominatim.openstreetmap.org/) | Geocoding & reverse geocoding | No |
| [Overpass](https://overpass-api.de/) | Hotels, transport stations, attractions (OSM) | No |
| [Wikipedia](https://en.wikipedia.org/api/rest_v1/) | City descriptions | No |
| [Open-Meteo](https://open-meteo.com/) | 3-day weather forecast | No |
| [Frankfurter](https://www.frankfurter.app/) | Currency exchange rates (ECB) | No |

## Author

**Berkay Han** — MSc Data Science, Berlin School of Business and Innovation (BSBI)

Module: Advanced Conversational UI Design and Chatbot Development  
Instructor: Dr. Abdelaziz Triki

## License

This project is submitted as coursework for academic evaluation. All rights reserved.
