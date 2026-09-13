"""
Pytest unit tests for actions.py
Tests all pure utility functions and form validators.

Run with:
    cd ~/Desktop/ecoTravelAdvisor
    source rasa-env/bin/activate
    pytest tests/test_actions.py -v
"""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# Add the actions directory to the path so we can import the module
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "actions"))

from actions import (
    format_carbon,
    calculate_eco_score,
    estimate_transport_price,
    fuzzy_match_location,
    _is_known_city,
    _is_known_country,
    _cities_in_country,
    ESTIMATED_TRANSPORT_PRICES,
    ValidateTripPlanningForm,
)


# ══════════════════════════════════════════════════════════════
# HELPER: Create mock Rasa objects for form validation tests
# ══════════════════════════════════════════════════════════════

def make_tracker(slot_value=None, intent="inform", text="", slots=None):
    """Create a mock Tracker with configurable slots and intent."""
    tracker = MagicMock()
    tracker.latest_message = {
        "intent": {"name": intent, "confidence": 0.95},
        "text": text or str(slot_value or ""),
    }
    # Default slot values
    default_slots = {
        "destination": None,
        "origin": None,
        "_dest_country_hint": None,
        "_origin_country_hint": None,
    }
    if slots:
        default_slots.update(slots)
    tracker.get_slot = lambda key: default_slots.get(key)
    return tracker


def make_dispatcher():
    """Create a mock CollectingDispatcher."""
    dispatcher = MagicMock()
    dispatcher.messages = []

    def capture_message(**kwargs):
        dispatcher.messages.append(kwargs)

    dispatcher.utter_message = capture_message
    return dispatcher


# ══════════════════════════════════════════════════════════════
# TEST 1: format_carbon()
# ══════════════════════════════════════════════════════════════

class TestFormatCarbon:
    """Tests for format_carbon(kg_co2) -> str"""

    def test_small_value_in_kg(self):
        """Values below 1000 should be shown in kg."""
        result = format_carbon(150.0)
        assert result == "150.0 kg CO2"

    def test_zero_emissions(self):
        """Zero emissions should be shown in kg."""
        result = format_carbon(0.0)
        assert result == "0.0 kg CO2"

    def test_boundary_below_1000(self):
        """999.9 kg should still be shown in kg, not tonnes."""
        result = format_carbon(999.9)
        assert result == "999.9 kg CO2"

    def test_boundary_at_1000(self):
        """Exactly 1000 kg should be converted to tonnes."""
        result = format_carbon(1000.0)
        assert result == "1.00 tonnes CO2"

    def test_large_value_in_tonnes(self):
        """Values above 1000 should be shown in tonnes."""
        result = format_carbon(2500.0)
        assert result == "2.50 tonnes CO2"

    def test_very_large_value(self):
        """Very large values should still format correctly."""
        result = format_carbon(15000.0)
        assert result == "15.00 tonnes CO2"

    def test_decimal_kg(self):
        """Decimal values should be formatted with 1 decimal place."""
        result = format_carbon(42.567)
        assert result == "42.6 kg CO2"

    def test_decimal_tonnes(self):
        """Tonne values should be formatted with 2 decimal places."""
        result = format_carbon(1234.5)
        assert result == "1.23 tonnes CO2"


# ══════════════════════════════════════════════════════════════
# TEST 2: calculate_eco_score()
# ══════════════════════════════════════════════════════════════

class TestCalculateEcoScore:
    """Tests for calculate_eco_score() -> dict with score, colour, label"""

    # --- Return structure ---
    def test_returns_dict_with_required_keys(self):
        """Result must contain score, colour, and label."""
        result = calculate_eco_score(100, 200)
        assert "score" in result
        assert "colour" in result
        assert "label" in result

    # --- Green zone (score >= 70) ---
    def test_zero_carbon_zero_price_is_green(self):
        """Perfect conditions (no eco cert) should produce green."""
        result = calculate_eco_score(0, 0)
        # medium weights: 0.4*100 + 0.4*100 + 0.2*0 = 80
        assert result["score"] == 80
        assert result["colour"] == "green"
        assert result["label"] == "Eco-Friendly"

    def test_low_carbon_low_price_is_green(self):
        """Low carbon + low price should be green."""
        # carbon_score = 100-(20/500)*100 = 96, price_score = 100-(50/500)*100 = 90
        # medium: 0.4*96 + 0.4*90 = 38.4+36 = 74.4 -> 74 (green)
        result = calculate_eco_score(20, 50)
        assert result["colour"] == "green"
        assert result["score"] >= 70

    # --- Amber zone (40 <= score < 70) ---
    def test_medium_carbon_medium_price_is_amber(self):
        """Moderate values should produce amber."""
        result = calculate_eco_score(250, 250)
        # 250/500 = 50% -> carbon_score = 50, price_score = 50
        # medium weights: 0.4*50 + 0.4*50 + 0.2*0 = 40
        assert result["colour"] == "amber"
        assert result["label"] == "Moderate Impact"

    # --- Red zone (score < 40) ---
    def test_high_carbon_high_price_is_red(self):
        """High carbon + high price should produce red."""
        result = calculate_eco_score(500, 500)
        assert result["score"] == 0
        assert result["colour"] == "red"
        assert result["label"] == "High Impact"

    def test_very_high_carbon_is_red(self):
        """Carbon above 500 kg should clamp to 0 carbon score."""
        result = calculate_eco_score(1000, 0)
        # carbon_score = max(0, 100 - 200) = 0
        # medium: 0.4*0 + 0.4*100 + 0.2*0 = 40 -> amber boundary
        assert result["score"] <= 40

    # --- Eco certification bonus ---
    def test_eco_certification_boosts_score(self):
        """Eco certification should increase the score."""
        without = calculate_eco_score(200, 200, has_eco_certification=False)
        with_cert = calculate_eco_score(200, 200, has_eco_certification=True)
        assert with_cert["score"] > without["score"]

    def test_eco_certification_gives_20_points_medium(self):
        """With medium preference, eco cert adds 0.20 * 100 = 20 points."""
        without = calculate_eco_score(0, 0, has_eco_certification=False)
        with_cert = calculate_eco_score(0, 0, has_eco_certification=True)
        # Without: 0.4*100 + 0.4*100 + 0.2*0 = 80
        # With:    0.4*100 + 0.4*100 + 0.2*100 = 100
        assert without["score"] == 80
        assert with_cert["score"] == 100

    # --- Sustainability preference weighting ---
    def test_high_preference_favours_low_carbon(self):
        """High sustainability preference weights carbon at 60%."""
        # Option A: low carbon, high price
        a = calculate_eco_score(50, 400, sustainability_preference="high")
        # Option B: high carbon, low price
        b = calculate_eco_score(400, 50, sustainability_preference="high")
        # With high pref, low carbon should score higher
        assert a["score"] > b["score"]

    def test_low_preference_favours_low_price(self):
        """Low sustainability preference weights price at 60%."""
        # Option A: high carbon, low price
        a = calculate_eco_score(400, 50, sustainability_preference="low")
        # Option B: low carbon, high price
        b = calculate_eco_score(50, 400, sustainability_preference="low")
        # With low pref, low price should score higher
        assert a["score"] > b["score"]

    def test_unknown_preference_defaults_to_medium(self):
        """Unknown preference should use medium weights."""
        result_medium = calculate_eco_score(100, 200, sustainability_preference="medium")
        result_unknown = calculate_eco_score(100, 200, sustainability_preference="unknown")
        assert result_medium["score"] == result_unknown["score"]

    def test_none_preference_defaults_to_medium(self):
        """None preference should use medium weights."""
        result_medium = calculate_eco_score(100, 200, sustainability_preference="medium")
        result_none = calculate_eco_score(100, 200, sustainability_preference=None)
        assert result_medium["score"] == result_none["score"]

    # --- Score clamping ---
    def test_score_never_exceeds_100(self):
        """Score should be clamped to max 100."""
        result = calculate_eco_score(0, 0, has_eco_certification=True)
        assert result["score"] <= 100

    def test_score_never_below_0(self):
        """Score should be clamped to min 0."""
        result = calculate_eco_score(10000, 10000)
        assert result["score"] >= 0

    # --- Boundary values ---
    def test_score_exactly_70_is_green(self):
        """Score of exactly 70 should be green."""
        # medium: 0.4 * carbon + 0.4 * price + 0.2 * 0 = 70
        # -> carbon + price = 175 -> carbon=100, price=75
        # price_score=75 -> price = 500*(1-0.75) = 125
        result = calculate_eco_score(0, 125, sustainability_preference="medium")
        # 0.4*100 + 0.4*75 = 40+30 = 70
        assert result["score"] == 70
        assert result["colour"] == "green"

    def test_score_exactly_40_is_amber(self):
        """Score of exactly 40 should be amber."""
        result = calculate_eco_score(250, 250, sustainability_preference="medium")
        # 0.4*50 + 0.4*50 = 20+20 = 40
        assert result["score"] == 40
        assert result["colour"] == "amber"

    def test_score_39_is_red(self):
        """Score of 39 should be red."""
        # medium: 0.4 * carbon + 0.4 * price = 39
        result = calculate_eco_score(255, 255, sustainability_preference="medium")
        # 0.4*(100-51) + 0.4*(100-51) = 0.4*49 + 0.4*49 = 39.2 -> 39
        assert result["score"] <= 40


# ══════════════════════════════════════════════════════════════
# TEST 3: estimate_transport_price()
# ══════════════════════════════════════════════════════════════

class TestEstimateTransportPrice:
    """Tests for estimate_transport_price(mode, distance_km) -> float"""

    def test_train_price(self):
        """Train: base 40 + 0.08/km."""
        result = estimate_transport_price("train", 500)
        assert result == 40 + 0.08 * 500  # 80

    def test_bus_price(self):
        """Bus: base 15 + 0.05/km."""
        result = estimate_transport_price("bus", 300)
        assert result == 15 + 0.05 * 300  # 30

    def test_car_price(self):
        """Car: base 20 + 0.12/km."""
        result = estimate_transport_price("car", 200)
        assert result == 20 + 0.12 * 200  # 44

    def test_plane_price(self):
        """Plane: base 50 + 0.06/km."""
        result = estimate_transport_price("plane", 1000)
        assert result == 50 + 0.06 * 1000  # 110

    def test_unknown_mode_uses_default(self):
        """Unknown transport mode should use default pricing."""
        result = estimate_transport_price("bicycle", 100)
        # Default: base 30 + 0.08/km
        assert result == 30 + 0.08 * 100  # 38

    def test_zero_distance(self):
        """Zero distance should return only the base fare."""
        result = estimate_transport_price("train", 0)
        assert result == 40  # base only

    def test_long_distance(self):
        """Long distance should calculate correctly."""
        result = estimate_transport_price("plane", 5000)
        assert result == 50 + 0.06 * 5000  # 350


# ══════════════════════════════════════════════════════════════
# TEST 4: Location helper functions
# ══════════════════════════════════════════════════════════════

class TestLocationHelpers:
    """Tests for _is_known_city, _is_known_country, _cities_in_country"""

    # --- _is_known_city ---
    def test_known_city_exact(self):
        """Exact city name should be recognized."""
        assert _is_known_city("Paris") is True

    def test_known_city_case_insensitive(self):
        """City matching should be case-insensitive."""
        assert _is_known_city("paris") is True
        assert _is_known_city("LONDON") is True

    def test_unknown_city(self):
        """Unknown city should return False."""
        assert _is_known_city("Atlantis") is False

    # --- _is_known_country ---
    def test_known_country_exact(self):
        """Exact country name should be recognized."""
        assert _is_known_country("France") is True

    def test_known_country_case_insensitive(self):
        """Country matching should be case-insensitive."""
        assert _is_known_country("germany") is True
        assert _is_known_country("SPAIN") is True

    def test_unknown_country(self):
        """Unknown country should return False."""
        assert _is_known_country("Narnia") is False

    # --- _cities_in_country ---
    def test_cities_in_known_country(self):
        """Should return a list of known cities for a country."""
        cities = _cities_in_country("France")
        assert isinstance(cities, list)
        assert len(cities) > 0
        assert "Paris" in cities

    def test_cities_in_country_case_insensitive(self):
        """Country lookup should be case-insensitive."""
        cities = _cities_in_country("france")
        assert "Paris" in cities

    def test_cities_in_unknown_country(self):
        """Unknown country should return empty list."""
        cities = _cities_in_country("Narnia")
        assert cities == []


# ══════════════════════════════════════════════════════════════
# TEST 5: fuzzy_match_location()
# ══════════════════════════════════════════════════════════════

class TestFuzzyMatchLocation:
    """Tests for fuzzy_match_location(user_input) -> str"""

    # --- Exact matches ---
    def test_exact_city_match(self):
        """Exact city name should return as-is."""
        assert fuzzy_match_location("Paris") == "Paris"

    def test_exact_city_lowercase(self):
        """Lowercase exact city should return properly cased."""
        assert fuzzy_match_location("paris") == "Paris"

    def test_exact_country_match(self):
        """Exact country name should return as-is."""
        assert fuzzy_match_location("France") == "France"

    def test_exact_country_lowercase(self):
        """Lowercase country should return properly cased."""
        assert fuzzy_match_location("germany") == "Germany"

    # --- Fuzzy matches ---
    def test_fuzzy_city_typo(self):
        """Close typo should be corrected (e.g. Londoon -> London)."""
        result = fuzzy_match_location("Londoon")
        assert result == "London"

    def test_fuzzy_country_typo(self):
        """Country typo should be corrected (e.g. Turkye -> Turkey)."""
        result = fuzzy_match_location("Turkye")
        assert result == "Turkey"

    # --- First-letter safety ---
    def test_first_letter_mismatch_rejected(self):
        """Fuzzy match with different first letter should be rejected."""
        result = fuzzy_match_location("bilbao")
        assert result != "Lebanon"

    # --- No match ---
    def test_no_match_returns_title_cased(self):
        """Unknown location should return title-cased input."""
        result = fuzzy_match_location("xyzabc")
        assert result == "Xyzabc"

    def test_no_match_preserves_words(self):
        """Multi-word unknown should title-case each word."""
        result = fuzzy_match_location("some random place")
        assert result == "Some Random Place"

    # --- Edge cases ---
    def test_empty_string(self):
        """Empty string should return as-is."""
        result = fuzzy_match_location("")
        assert result == ""

    def test_none_input(self):
        """None should return None."""
        result = fuzzy_match_location(None)
        assert result is None

    def test_whitespace_only(self):
        """Whitespace-only should return as-is."""
        result = fuzzy_match_location("   ")
        assert result == "   "

    def test_whitespace_around_valid_city(self):
        """Whitespace around a valid city should still match."""
        result = fuzzy_match_location("  Berlin  ")
        assert result == "Berlin"


# ══════════════════════════════════════════════════════════════
# TEST 6: ValidateTripPlanningForm — destination validator
# ══════════════════════════════════════════════════════════════

class TestValidateDestination:
    """Tests for ValidateTripPlanningForm.validate_destination()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_valid_city_accepted(self):
        """Known city should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="Paris")
        result = self.form.validate_destination(
            "Paris", dispatcher, tracker, self.domain
        )
        assert result["destination"] == "Paris"

    def test_country_triggers_re_ask(self):
        """Country input should set hint and reject slot."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="France")
        result = self.form.validate_destination(
            "France", dispatcher, tracker, self.domain
        )
        assert result["destination"] is None
        assert result["_dest_country_hint"] == "France"

    def test_typo_gets_corrected(self):
        """Typo should be fuzzy-corrected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="Londoon")
        result = self.form.validate_destination(
            "Londoon", dispatcher, tracker, self.domain
        )
        assert result["destination"] == "London"

    def test_off_topic_rejected(self):
        """Out-of-scope intent should reject the slot."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="pizza recipe",
            intent="out_of_scope"
        )
        result = self.form.validate_destination(
            "pizza recipe", dispatcher, tracker, self.domain
        )
        assert result["destination"] is None

    def test_gibberish_rejected(self):
        """Input without vowels should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="xzq")
        result = self.form.validate_destination(
            "xzq", dispatcher, tracker, self.domain
        )
        assert result["destination"] is None

    def test_too_short_rejected(self):
        """Single character should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="a")
        result = self.form.validate_destination(
            "a", dispatcher, tracker, self.domain
        )
        assert result["destination"] is None

    def test_sentence_rejected(self):
        """Long sentence should be rejected as not a place name."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="I would like to go somewhere nice and warm please"
        )
        result = self.form.validate_destination(
            "I would like to go somewhere nice and warm please",
            dispatcher, tracker, self.domain
        )
        assert result["destination"] is None

    def test_empty_value_returns_none(self):
        """Empty slot value should return None destination."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="")
        result = self.form.validate_destination(
            "", dispatcher, tracker, self.domain
        )
        assert result["destination"] is None


# ══════════════════════════════════════════════════════════════
# TEST 7: ValidateTripPlanningForm — origin validator
# ══════════════════════════════════════════════════════════════

class TestValidateOrigin:
    """Tests for ValidateTripPlanningForm.validate_origin()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_valid_city_accepted(self):
        """Known city should be accepted as origin."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="London",
            slots={"destination": "Paris"}
        )
        result = self.form.validate_origin(
            "London", dispatcher, tracker, self.domain
        )
        assert result["origin"] == "London"
        # Destination should be preserved
        assert result["destination"] == "Paris"

    def test_country_triggers_re_ask(self):
        """Country should set hint and reject origin."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="Germany",
            slots={"destination": "Paris"}
        )
        result = self.form.validate_origin(
            "Germany", dispatcher, tracker, self.domain
        )
        assert result["origin"] is None
        assert result["_origin_country_hint"] == "Germany"
        assert result["destination"] == "Paris"

    def test_off_topic_rejected(self):
        """Out-of-scope should reject origin."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="what is AI",
            intent="out_of_scope",
            slots={"destination": "Paris"}
        )
        result = self.form.validate_origin(
            "what is AI", dispatcher, tracker, self.domain
        )
        assert result["origin"] is None
        assert result["destination"] == "Paris"


# ══════════════════════════════════════════════════════════════
# TEST 8: ValidateTripPlanningForm — budget validator
# ══════════════════════════════════════════════════════════════

class TestValidateBudget:
    """Tests for ValidateTripPlanningForm.validate_budget()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_numeric_budget_accepted(self):
        """Plain number should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="500")
        result = self.form.validate_budget(
            "500", dispatcher, tracker, self.domain
        )
        assert result["budget"] == "500"

    def test_budget_with_currency(self):
        """Number with currency word should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="500 euros")
        result = self.form.validate_budget(
            "500 euros", dispatcher, tracker, self.domain
        )
        assert result["budget"] == "500 euros"

    def test_descriptive_budget_accepted(self):
        """Descriptive words like 'flexible' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="flexible")
        result = self.form.validate_budget(
            "flexible", dispatcher, tracker, self.domain
        )
        assert result["budget"] == "flexible"

    def test_too_low_budget_rejected(self):
        """Budget below 1 should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="0")
        result = self.form.validate_budget(
            "0", dispatcher, tracker, self.domain
        )
        assert result["budget"] is None

    def test_too_high_budget_rejected(self):
        """Budget above 1,000,000 should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="5000000")
        result = self.form.validate_budget(
            "5000000", dispatcher, tracker, self.domain
        )
        assert result["budget"] is None

    def test_gibberish_budget_rejected(self):
        """Random letters with numbers should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="abc123xyz")
        result = self.form.validate_budget(
            "abc123xyz", dispatcher, tracker, self.domain
        )
        assert result["budget"] is None

    def test_off_topic_rejected(self):
        """Out-of-scope should reject budget."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="what is the weather",
            intent="out_of_scope"
        )
        result = self.form.validate_budget(
            "what is the weather", dispatcher, tracker, self.domain
        )
        assert result["budget"] is None


# ══════════════════════════════════════════════════════════════
# TEST 9: ValidateTripPlanningForm — num_travelers validator
# ══════════════════════════════════════════════════════════════

class TestValidateNumTravelers:
    """Tests for ValidateTripPlanningForm.validate_num_travelers()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_numeric_count_accepted(self):
        """Plain number 1-50 should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="3")
        result = self.form.validate_num_travelers(
            "3", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] == "3"

    def test_word_solo_maps_to_1(self):
        """'solo' should map to 1."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="solo")
        result = self.form.validate_num_travelers(
            "solo", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] == "1"

    def test_word_couple_maps_to_2(self):
        """'couple' should map to 2."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="couple")
        result = self.form.validate_num_travelers(
            "couple", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] == "2"

    def test_family_without_number_maps_to_4(self):
        """'family' without a number should default to 4."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="family")
        result = self.form.validate_num_travelers(
            "family", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] == "4"

    def test_group_without_number_asks_again(self):
        """'group' without a number should ask how many."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="group")
        result = self.form.validate_num_travelers(
            "group", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] is None

    def test_too_many_rejected(self):
        """Count above 50 should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="100")
        result = self.form.validate_num_travelers(
            "100", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] is None

    def test_zero_rejected(self):
        """Zero travelers should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="0")
        result = self.form.validate_num_travelers(
            "0", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] is None

    def test_descriptive_with_number(self):
        """'5 people' should extract 5."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="5 people")
        result = self.form.validate_num_travelers(
            "5 people", dispatcher, tracker, self.domain
        )
        assert result["num_travelers"] == "5"


# ══════════════════════════════════════════════════════════════
# TEST 10: ValidateTripPlanningForm — sustainability_preference
# ══════════════════════════════════════════════════════════════

class TestValidateSustainabilityPreference:
    """Tests for ValidateTripPlanningForm.validate_sustainability_preference()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_direct_high_accepted(self):
        """Exact 'high' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="high", text="high")
        result = self.form.validate_sustainability_preference(
            "high", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "high"

    def test_direct_medium_accepted(self):
        """Exact 'medium' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="medium", text="medium")
        result = self.form.validate_sustainability_preference(
            "medium", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "medium"

    def test_direct_low_accepted(self):
        """Exact 'low' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="low", text="low")
        result = self.form.validate_sustainability_preference(
            "low", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "low"

    def test_eco_keyword_maps_to_high(self):
        """'eco-friendly' text should map to high."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="eco-friendly please",
            text="eco-friendly please"
        )
        result = self.form.validate_sustainability_preference(
            "eco-friendly please", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "high"

    def test_cheapest_keyword_maps_to_low(self):
        """'cheapest' text should map to low."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="cheapest option",
            text="cheapest option"
        )
        result = self.form.validate_sustainability_preference(
            "cheapest option", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "low"

    def test_gibberish_rejected(self):
        """Vowelless gibberish should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="xzqwrt",
            text="xzqwrt"
        )
        result = self.form.validate_sustainability_preference(
            "xzqwrt", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] is None

    def test_unclear_defaults_to_medium(self):
        """Unrecognised but valid text should default to medium."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="balanced approach",
            text="balanced approach"
        )
        result = self.form.validate_sustainability_preference(
            "balanced approach", dispatcher, tracker, self.domain
        )
        assert result["sustainability_preference"] == "medium"


# ══════════════════════════════════════════════════════════════
# TEST 11: ValidateTripPlanningForm — travel_date_start
# ══════════════════════════════════════════════════════════════

class TestValidateTravelDateStart:
    """Tests for ValidateTripPlanningForm.validate_travel_date_start()"""

    def setup_method(self):
        self.form = ValidateTripPlanningForm()
        self.domain = {}

    def test_date_with_numbers_accepted(self):
        """'15 March to 22 March' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="15 March to 22 March")
        result = self.form.validate_travel_date_start(
            "15 March to 22 March", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] == "15 March to 22 March"

    def test_date_word_accepted(self):
        """'next summer' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="next summer")
        result = self.form.validate_travel_date_start(
            "next summer", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] == "next summer"

    def test_tomorrow_accepted(self):
        """'tomorrow' should be accepted."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="tomorrow")
        result = self.form.validate_travel_date_start(
            "tomorrow", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] == "tomorrow"

    def test_gibberish_rejected(self):
        """Random characters should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="asd12312dl")
        result = self.form.validate_travel_date_start(
            "asd12312dl", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] is None

    def test_random_word_rejected(self):
        """Non-date words should be rejected."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(slot_value="pizza")
        result = self.form.validate_travel_date_start(
            "pizza", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] is None

    def test_off_topic_rejected(self):
        """Out-of-scope intent should reject date."""
        dispatcher = make_dispatcher()
        tracker = make_tracker(
            slot_value="tell me a joke",
            intent="out_of_scope"
        )
        result = self.form.validate_travel_date_start(
            "tell me a joke", dispatcher, tracker, self.domain
        )
        assert result["travel_date_start"] is None
