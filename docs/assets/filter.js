(function () {
  function normalizeValue(value) {
    return String(value || "").trim().toLowerCase();
  }

  function parseScore(value) {
    var parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  }

  function getCards() {
    return Array.prototype.slice.call(document.querySelectorAll(".opportunity-card"));
  }

  function updateCounts(visible, total) {
    var visibleCount = document.getElementById("visible-count");
    var totalCount = document.getElementById("total-count");
    if (visibleCount) {
      visibleCount.textContent = String(visible);
    }
    if (totalCount) {
      totalCount.textContent = String(total);
    }
  }

  function applyFilters() {
    var themeSelect = document.getElementById("theme-filter");
    var partnerSelect = document.getElementById("partner-filter");
    var scoreInput = document.getElementById("score-filter");
    var scoreValue = document.getElementById("score-filter-value");

    var selectedTheme = normalizeValue(themeSelect ? themeSelect.value : "all");
    var selectedPartner = normalizeValue(partnerSelect ? partnerSelect.value : "all");
    var minimumScore = parseScore(scoreInput ? scoreInput.value : 0);

    if (scoreValue) {
      scoreValue.textContent = minimumScore.toFixed(2);
    }

    var cards = getCards();
    var visibleCount = 0;

    cards.forEach(function (card) {
      var cardTheme = normalizeValue(card.getAttribute("data-theme"));
      var cardPartner = normalizeValue(card.getAttribute("data-partner"));
      var cardScore = parseScore(card.getAttribute("data-score"));

      var themeMatch = selectedTheme === "all" || cardTheme === selectedTheme;
      var partnerMatch = selectedPartner === "all" || cardPartner === selectedPartner;
      var scoreMatch = cardScore >= minimumScore;
      var isVisible = themeMatch && partnerMatch && scoreMatch;

      card.style.display = isVisible ? "block" : "none";
      card.setAttribute("aria-hidden", isVisible ? "false" : "true");

      if (isVisible) {
        visibleCount += 1;
      }
    });

    updateCounts(visibleCount, cards.length);
  }

  function bindEvents() {
    var ids = ["theme-filter", "partner-filter", "score-filter"];
    ids.forEach(function (id) {
      var control = document.getElementById(id);
      if (!control) {
        return;
      }
      control.addEventListener("input", applyFilters);
      control.addEventListener("change", applyFilters);
    });
  }

  function init() {
    bindEvents();
    applyFilters();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
