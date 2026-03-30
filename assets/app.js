const FALLBACK_TIMEZONE = "Africa/Johannesburg";
const STAR_LEVELS = [5, 4, 3, 2, 1];
const WEEK_COLUMNS = 8;
const MONTH_COLUMNS = 6;
const BRANCH_THEME_COLORS = {
  "jhb-auto": "#0d3d7c",
  "germiston-commercial": "#1f5da8",
  "pretoria-manual-auto": "#3c79c3",
  "jhb-manual": "#76a7dc",
};
const METRIC_HELP = {
  "Data status": "Shows whether the dashboard is using live synced review data or fallback demo data.",
  "Last updated": "The timestamp of the most recent successful dashboard refresh.",
  Timezone: "The timezone used for dates, weekly buckets, and monthly totals.",
  "Total GBP reviews": "The total number of published Google Business Profile reviews across all tracked branches.",
  "Average rating": "The current average star rating across all published reviews in scope.",
  "Reviews in past 30 days": "How many new reviews were published in the last 30 days.",
  "Past 30-day rating": "The average star rating of reviews published in the last 30 days.",
  "Response rate": "The share of published reviews that currently show an owner response from the business.",
  "Comment rate": "The share of reviews that include written feedback instead of only a star rating.",
  "Local Guide share": "The share of reviews written by Google accounts marked as Local Guides.",
  "Reviews in last 7 days": "How many reviews were published in the last 7 days.",
  "Reviews this month": "How many reviews were published since the start of the current month.",
  "Last 7-day review rating": "The average star rating of reviews published in the last 7 days.",
  "Current GBP rating": "The current Google Business Profile star rating for this branch or view.",
  "5-star reviews needed for +0.1": "An estimate of how many additional 5-star reviews are needed to raise the displayed rating by 0.1.",
  "Last week 1-star impact": "The estimated rating effect caused by one-star reviews published in the last 7 days.",
  "Total reviews": "The current total published review count for this branch.",
  "Portfolio share": "This branch's share of the full published review portfolio.",
  Rating: "The current average star rating.",
  "30-day rating": "The average star rating of reviews published in the last 30 days.",
  "Ratings mix": "The current count of 5-star through 1-star reviews for this branch.",
};

const state = {
  data: null,
  focusBranchId: "",
  filters: {
    branchId: "all",
    rating: "all",
    dateRange: "all",
    search: "",
  },
};

document.addEventListener("DOMContentLoaded", async () => {
  hydrateBrandImages();
  wireFilters();
  wireBackToTop();

  try {
    const response = await fetch(`./data/reviews.json?v=${Date.now()}`, {
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Failed to load dashboard data (${response.status})`);
    }

    state.data = repairDashboardData(await response.json());
    renderDashboard();
  } catch (error) {
    renderFailure(error);
  }
});

function hydrateBrandImages() {
  document.querySelectorAll("[data-logo-frame]").forEach((frame) => {
    const img = frame.querySelector("[data-logo]");
    const syncState = () => {
      if (img.complete && img.naturalWidth > 0) {
        frame.classList.add("has-image");
      } else if (img.complete) {
        frame.classList.remove("has-image");
      }
    };

    img.addEventListener("load", () => {
      syncState();
    });

    img.addEventListener("error", () => {
      frame.classList.remove("has-image");
    });

    syncState();
  });
}

function wireFilters() {
  document.getElementById("focusBranchButtons").addEventListener("click", (event) => {
    const button = event.target.closest("[data-focus-branch]");

    if (!button) {
      return;
    }

    activateFocusBranch(button.getAttribute("data-focus-branch"));
  });

  document.getElementById("branchFilter").addEventListener("change", (event) => {
    state.filters.branchId = event.target.value;
    renderReviews();
  });

  document.getElementById("ratingFilter").addEventListener("change", (event) => {
    state.filters.rating = event.target.value;
    renderReviews();
  });

  document.getElementById("dateFilter").addEventListener("change", (event) => {
    state.filters.dateRange = event.target.value;
    renderReviews();
  });

  document.getElementById("searchFilter").addEventListener("input", (event) => {
    state.filters.search = event.target.value.trim().toLowerCase();
    renderReviews();
  });
}

function wireBackToTop() {
  const button = document.getElementById("backToTop");

  if (!button) {
    return;
  }

  const syncVisibility = () => {
    button.classList.toggle("is-visible", window.scrollY > 360);
  };

  button.addEventListener("click", () => {
    window.scrollTo({
      top: 0,
      behavior: "smooth",
    });
  });

  window.addEventListener("scroll", syncVisibility, { passive: true });
  syncVisibility();
}

function activateFocusBranch(branchId) {
  if (!branchId) {
    return;
  }

  state.focusBranchId = branchId;
  state.filters.branchId = branchId;
  renderDashboard();
}

function renderMetricLabel(label, className = "") {
  const description = METRIC_HELP[label];
  const classes = ["metric-label", className, description ? "has-help" : ""]
    .filter(Boolean)
    .join(" ");

  if (!description) {
    return `<span class="${classes}">${escapeHtml(label)}</span>`;
  }

  return `
    <span
      class="${classes}"
      data-tooltip="${escapeAttribute(description)}"
    >
      ${escapeHtml(label)}
      <span class="metric-help-dot" aria-hidden="true">?</span>
    </span>
  `;
}

function renderDashboard() {
  const data = state.data;
  const timezone = data.meta?.timezone || FALLBACK_TIMEZONE;
  const computed = buildComputedModel(data, timezone);

  if (!computed.branches.length) {
    renderFailure(new Error("No branch data is available."));
    return;
  }

  if (!computed.branches.some((branch) => branch.id === state.focusBranchId)) {
    state.focusBranchId = computed.branches[0].id;
  }

  if (state.filters.branchId === "all") {
    state.filters.branchId = state.focusBranchId;
  }

  state.computed = computed;
  populateHeader(data, timezone);
  populateBranchControls(computed.branches);
  renderFocusSection(computed);
  renderSummaryCards(computed);
  renderBranchCards(computed.branches);
  renderTrendPanels(computed);
  renderLeaderboard(computed);
  renderDistributionTable(computed);
  renderCalendarTable("week", computed.weeklyColumns, computed.branches);
  renderCalendarTable("month", computed.monthlyColumns, computed.branches);
  renderAttentionList(computed);
  renderReviews();
}

function repairDashboardData(data) {
  const branches = (data.branches || []).map((branch) => applyBranchTheme(branch));
  const repairedReviews = repairReviewAssignments(data.reviews || [], branches);

  return {
    ...data,
    branches,
    reviews: repairedReviews,
    meta: {
      ...data.meta,
      repairedAtRender: repairedReviews.length !== (data.reviews || []).length,
    },
  };
}

function applyBranchTheme(branch) {
  return {
    ...branch,
    color: BRANCH_THEME_COLORS[branch.id] || branch.color || "#0d3d7c",
  };
}

function repairReviewAssignments(reviews, branches) {
  const deduped = new Map();

  reviews.forEach((review) => {
    const branch = resolveReviewBranch(review, branches);

    if (!branch) {
      return;
    }

    const repairedReview = {
      ...review,
      branchId: branch.id,
      branchName: branch.name,
    };

    deduped.set(`${repairedReview.branchId}::${repairedReview.id}`, repairedReview);
  });

  return [...deduped.values()].sort(
    (left, right) => new Date(right.publishedAt || right.scrapedAt) - new Date(left.publishedAt || left.scrapedAt)
  );
}

function resolveReviewBranch(review, branches) {
  const reviewPlaceId = normalizeMatchToken(review.placeId);

  if (reviewPlaceId) {
    const placeMatch = branches.find((branch) => normalizeMatchToken(branch.placeId) === reviewPlaceId);
    if (placeMatch) {
      return placeMatch;
    }
  }

  const reviewCid = normalizeMatchToken(review.cid);

  if (reviewCid) {
    const cidMatch = branches.find((branch) => normalizeMatchToken(branch.cid) === reviewCid);
    if (cidMatch) {
      return cidMatch;
    }
  }

  const reviewTitle = normalizeMatchText(review.title);

  if (!reviewTitle) {
    return null;
  }

  return (
    branches.find((branch) => getBranchMatchCandidates(branch).some((candidate) => candidate === reviewTitle)) ||
    branches.find((branch) => getBranchMatchCandidates(branch).some((candidate) => (
      candidate &&
      (reviewTitle.startsWith(candidate) || candidate.startsWith(reviewTitle))
    ))) ||
    null
  );
}

function getBranchMatchCandidates(branch) {
  return [
    branch.name,
    branch.shortName,
    branch.searchQuery,
    ...(branch.aliases || []),
  ]
    .map(normalizeMatchText)
    .filter(Boolean);
}

function buildComputedModel(data, timezone) {
  const branches = (data.branches || []).map((branch) => ({
    ...branch,
    reviews: [],
  }));

  const branchMap = new Map(branches.map((branch) => [branch.id, branch]));
  const reviews = (data.reviews || [])
    .map((review) => ({
      ...review,
      rating: Number(review.rating) || 0,
      publishedAt: review.publishedAt || review.scrapedAt,
    }))
    .filter((review) => branchMap.has(review.branchId))
    .sort((left, right) => new Date(right.publishedAt) - new Date(left.publishedAt));

  reviews.forEach((review) => {
    branchMap.get(review.branchId).reviews.push(review);
  });

  branches.forEach((branch) => {
    const fallbackCount = branch.reviews.length;
    const fallbackRating = average(branch.reviews.map((review) => review.rating));

    branch.currentReviewsCount = isFiniteNumber(branch.currentReviewsCount) && Number(branch.currentReviewsCount) > 0
      ? Number(branch.currentReviewsCount)
      : fallbackCount;
    branch.currentRating = isFiniteNumber(branch.currentRating) && Number(branch.currentRating) > 0
      ? Number(branch.currentRating)
      : fallbackRating;
    branch.starCounts = computeStarCounts(branch.reviews);
    branch.latestReview = branch.reviews[0] || null;
    branch.thisMonthCount = countSince(branch.reviews, 30);
    branch.thisWeekCount = countSince(branch.reviews, 7);
    branch.currentMonthCount = countCurrentMonth(branch.reviews, timezone);
    branch.trackedReviewCount = branch.reviews.length;
    branch.ownerResponseCount = branch.reviews.filter(hasOwnerResponse).length;
    branch.ownerResponseRate = percentage(branch.ownerResponseCount, branch.trackedReviewCount);
    branch.commentCount = branch.reviews.filter(hasWrittenComment).length;
    branch.commentRate = percentage(branch.commentCount, branch.trackedReviewCount);
    branch.localGuideCount = branch.reviews.filter((review) => Boolean(review.isLocalGuide)).length;
    branch.localGuideShare = percentage(branch.localGuideCount, branch.trackedReviewCount);
    branch.lowStarCount = branch.reviews.filter((review) => review.rating <= 2).length;
    branch.lowStarShare = percentage(branch.lowStarCount, branch.trackedReviewCount);
    branch.positiveCount = branch.reviews.filter((review) => review.rating >= 4).length;
    branch.positiveShare = percentage(branch.positiveCount, branch.trackedReviewCount);
    branch.last7Stats = periodStats(branch.reviews, 0, 7);
    branch.last30Stats = periodStats(branch.reviews, 0, 30);
    branch.previous30Stats = periodStats(branch.reviews, 30, 30);
    branch.ratingDelta30 = branch.last30Stats.averageRating - branch.previous30Stats.averageRating;
    branch.volumeDelta30 = branch.last30Stats.count - branch.previous30Stats.count;
    branch.lastWeekOneStarCount = countMatchingSince(branch.reviews, 7, (review) => review.rating === 1);
    branch.lastWeekOneStarEffect = estimateOneStarImpact(
      branch.currentRating,
      branch.currentReviewsCount,
      branch.lastWeekOneStarCount
    );
    branch.fiveStarReviewsForPointOne = estimateFiveStarReviewsForLift(
      branch.currentRating,
      branch.currentReviewsCount
    );
    branch.shareOfPortfolio = percentage(branch.currentReviewsCount, 0);
  });

  const overallFromBranches = branches.reduce(
    (accumulator, branch) => {
      const reviewCount = Number(branch.currentReviewsCount) || 0;
      const rating = Number(branch.currentRating) || 0;
      accumulator.reviewCount += reviewCount;
      accumulator.weightedRating += rating * reviewCount;
      return accumulator;
    },
    { reviewCount: 0, weightedRating: 0 }
  );

  const overall = {
    totalReviews: overallFromBranches.reviewCount || reviews.length,
    currentRating: overallFromBranches.reviewCount
      ? overallFromBranches.weightedRating / overallFromBranches.reviewCount
      : average(reviews.map((review) => review.rating)),
    starCounts: computeStarCounts(reviews),
    reviewsLast30Days: countSince(reviews, 30),
    reviewsLast7Days: countSince(reviews, 7),
    latestReviewAt: reviews[0]?.publishedAt || data.meta?.generatedAt || null,
    trackedReviewCount: reviews.length,
    ownerResponseCount: reviews.filter(hasOwnerResponse).length,
    ownerResponseRate: percentage(reviews.filter(hasOwnerResponse).length, reviews.length),
    commentCount: reviews.filter(hasWrittenComment).length,
    commentRate: percentage(reviews.filter(hasWrittenComment).length, reviews.length),
    localGuideCount: reviews.filter((review) => Boolean(review.isLocalGuide)).length,
    localGuideShare: percentage(reviews.filter((review) => Boolean(review.isLocalGuide)).length, reviews.length),
    lowStarCount: reviews.filter((review) => review.rating <= 2).length,
    lowStarShare: percentage(reviews.filter((review) => review.rating <= 2).length, reviews.length),
    positiveCount: reviews.filter((review) => review.rating >= 4).length,
    positiveShare: percentage(reviews.filter((review) => review.rating >= 4).length, reviews.length),
    last30Stats: periodStats(reviews, 0, 30),
    previous30Stats: periodStats(reviews, 30, 30),
  };
  overall.ratingDelta30 = overall.last30Stats.averageRating - overall.previous30Stats.averageRating;
  overall.volumeDelta30 = overall.last30Stats.count - overall.previous30Stats.count;

  const weeklyColumns = buildPeriodColumns("week", timezone, WEEK_COLUMNS);
  const monthlyColumns = buildPeriodColumns("month", timezone, MONTH_COLUMNS);
  const totalPortfolioReviews = branches.reduce((sum, branch) => sum + branch.currentReviewsCount, 0);

  branches.forEach((branch) => {
    branch.weeklyBuckets = bucketReviews(branch.reviews, weeklyColumns, "week", timezone);
    branch.monthlyBuckets = bucketReviews(branch.reviews, monthlyColumns, "month", timezone);
    branch.shareOfPortfolio = percentage(branch.currentReviewsCount, totalPortfolioReviews);
  });

  const weeklyTotals = bucketReviews(reviews, weeklyColumns, "week", timezone);
  const monthlyTotals = bucketReviews(reviews, monthlyColumns, "month", timezone);
  const rankedBranches = [...branches].sort(compareBranchPerformance);
  const attentionReviews = reviews
    .filter((review) => review.rating <= 3 && !hasOwnerResponse(review))
    .slice(0, 6);

  return {
    timezone,
    branches,
    reviews,
    overall,
    weeklyColumns,
    monthlyColumns,
    weeklyTotals,
    monthlyTotals,
    rankedBranches,
    attentionReviews,
  };
}

function populateHeader(data, timezone) {
  const mode = data.meta?.mode === "live" ? "Live data" : "Demo data";
  const modeClass = data.meta?.mode === "live" ? "live" : "demo";
  const modeTarget = document.getElementById("dataMode");

  modeTarget.innerHTML = `<span class="status-pill ${modeClass}">${escapeHtml(mode)}</span>`;
  document.getElementById("generatedAt").textContent = formatDateTime(
    data.meta?.generatedAt,
    timezone
  );
  document.getElementById("dashboardTimezone").textContent = timezone;
}

function populateBranchControls(branches) {
  const focusBranchButtons = document.getElementById("focusBranchButtons");
  const branchFilter = document.getElementById("branchFilter");
  const dateFilter = document.getElementById("dateFilter");

  focusBranchButtons.innerHTML = branches
    .map(
      (branch) =>
        `<button
          type="button"
          class="focus-branch-button${branch.id === state.focusBranchId ? " is-active" : ""}"
          data-focus-branch="${escapeHtml(branch.id)}"
          style="--branch-color: ${escapeHtml(branch.color || "#0d3d7c")}"
          aria-pressed="${branch.id === state.focusBranchId ? "true" : "false"}"
        >
          ${escapeHtml(branch.shortName || branch.name)}
        </button>`
    )
    .join("");

  branchFilter.innerHTML = [
    `<option value="all">All branches</option>`,
    ...branches.map(
      (branch) =>
        `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.shortName || branch.name)}</option>`
    ),
  ].join("");

  branchFilter.value = state.filters.branchId;
  dateFilter.value = state.filters.dateRange;
}

function renderFocusSection(model) {
  const branch = getFocusBranch(model);
  const lastReviewText = branch.latestReview
    ? `Latest review on ${formatDate(branch.latestReview.publishedAt, model.timezone)}`
    : "No recent review date available";

  document.getElementById("focusBranchTitle").textContent = branch.shortName || branch.name;
  document.getElementById("focusBranchNote").textContent = (
    `${branch.name} currently holds a ${formatRating(branch.currentRating)} rating across ` +
    `${formatInteger(branch.currentReviewsCount)} published reviews. ${lastReviewText}.`
  );

  const targetRating = Math.min(5, roundToOneDecimal(branch.currentRating + 0.1));
  const oneStarEffectDetail = branch.lastWeekOneStarCount
    ? `${formatInteger(branch.lastWeekOneStarCount)} one-star review${branch.lastWeekOneStarCount === 1 ? "" : "s"} in the past 7 days`
    : "No one-star reviews in the past 7 days";

  const cards = [
    {
      label: "Reviews in last 7 days",
      value: formatInteger(branch.thisWeekCount),
      detail: "Published in the past 7 days",
      tone: "accent",
    },
    {
      label: "Reviews this month",
      value: formatInteger(branch.currentMonthCount),
      detail: "Month to date",
      tone: "neutral",
    },
    {
      label: "Last 7-day review rating",
      value: branch.last7Stats.count ? formatRating(branch.last7Stats.averageRating) : "N/A",
      detail: `${formatInteger(branch.last7Stats.count)} recent reviews`,
      tone: "neutral",
    },
    {
      label: "Current GBP rating",
      value: formatRating(branch.currentRating),
      detail: `${formatInteger(branch.currentReviewsCount)} total published reviews`,
      tone: "success",
    },
    {
      label: "5-star reviews needed for +0.1",
      value: branch.currentRating >= 4.95 ? "0" : formatInteger(branch.fiveStarReviewsForPointOne),
      detail: branch.currentRating >= 4.95
        ? "Already very close to a 5.0 rating"
        : `Estimated lift from ${formatRating(branch.currentRating)} to ${formatRating(targetRating)}`,
      tone: "accent",
    },
    {
      label: "Last week 1-star impact",
      value: formatSignedDecimal(branch.lastWeekOneStarEffect),
      detail: oneStarEffectDetail,
      tone: branch.lastWeekOneStarCount ? "danger" : "neutral",
    },
  ];

  document.getElementById("focusCards").innerHTML = cards
    .map(
      (card) => `
        <article class="focus-card ${escapeHtml(card.tone)}">
          ${renderMetricLabel(card.label, "focus-card-label")}
          <strong>${escapeHtml(card.value)}</strong>
          <p>${escapeHtml(card.detail)}</p>
        </article>
      `
    )
    .join("");
}

function renderTrendPanels(model) {
  const branch = getFocusBranch(model);
  const branchLabel = branch.shortName || branch.name;

  document.getElementById("weeklyTrendNote").textContent = `Last 8 weeks for ${branchLabel}`;
  document.getElementById("monthlyTrendNote").textContent = `Last 6 months for ${branchLabel}`;

  renderTrendChart(document.getElementById("weeklyTrend"), branch.weeklyBuckets);
  renderTrendChart(document.getElementById("monthlyTrend"), branch.monthlyBuckets);
}

function renderSummaryCards(model) {
  const cards = [
    {
      label: "Total GBP reviews",
      value: formatInteger(model.overall.totalReviews),
    },
    {
      label: "Average rating",
      value: formatRating(model.overall.currentRating),
    },
    {
      label: "Reviews in past 30 days",
      value: formatInteger(model.overall.reviewsLast30Days),
    },
    {
      label: "Past 30-day rating",
      value: formatRating(model.overall.last30Stats.averageRating),
    },
    {
      label: "Response rate",
      value: formatPercent(model.overall.ownerResponseRate),
    },
    {
      label: "Comment rate",
      value: formatPercent(model.overall.commentRate),
    },
    {
      label: "Local Guide share",
      value: formatPercent(model.overall.localGuideShare),
    },
  ];

  document.getElementById("summaryCards").innerHTML = cards
    .map(
      (card) => `
        <article class="summary-card">
          ${renderMetricLabel(card.label, "summary-card-label")}
          <strong>${escapeHtml(card.value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderBranchCards(branches) {
  const container = document.getElementById("branchCards");

  if (!branches.length) {
    container.innerHTML = getEmptyState();
    return;
  }

  container.innerHTML = branches
    .map((branch) => {
      const targetRating = Math.min(5, roundToOneDecimal(branch.currentRating + 0.1));
      const lastWeekOneStarDetail = branch.lastWeekOneStarCount
        ? `${formatInteger(branch.lastWeekOneStarCount)} one-star in last 7 days`
        : "No one-star reviews in last 7 days";
      const last7RatingValue = branch.last7Stats.count ? formatRating(branch.last7Stats.averageRating) : "N/A";
      const last7RatingDetail = branch.last7Stats.count
        ? `${formatInteger(branch.last7Stats.count)} recent reviews`
        : "No recent reviews";

      const primaryStats = [
        {
          label: "Current GBP rating",
          value: formatRating(branch.currentRating),
          detail: `${renderTextStars(branch.currentRating)} live rating`,
          tone: "success",
        },
        {
          label: "Total reviews",
          value: formatInteger(branch.currentReviewsCount),
          detail: "Published reviews",
          tone: "neutral",
        },
      ];

      const comparisonStats = [
        {
          label: "Reviews in last 7 days",
          value: formatInteger(branch.thisWeekCount),
          detail: "Published in the past 7 days",
          tone: "accent",
        },
        {
          label: "Reviews this month",
          value: formatInteger(branch.currentMonthCount),
          detail: "Month to date",
          tone: "neutral",
        },
        {
          label: "Last 7-day review rating",
          value: last7RatingValue,
          detail: last7RatingDetail,
          tone: "neutral",
        },
        {
          label: "5-star reviews needed for +0.1",
          value: branch.currentRating >= 4.95 ? "0" : formatInteger(branch.fiveStarReviewsForPointOne),
          detail: branch.currentRating >= 4.95
            ? "Already very close to 5.0"
            : `Estimated lift from ${formatRating(branch.currentRating)} to ${formatRating(targetRating)}`,
          tone: "accent",
        },
        {
          label: "Last week 1-star impact",
          value: formatSignedDecimal(branch.lastWeekOneStarEffect),
          detail: lastWeekOneStarDetail,
          tone: branch.lastWeekOneStarCount ? "danger" : "neutral",
        },
        {
          label: "Response rate",
          value: formatPercent(branch.ownerResponseRate),
          detail: `${formatInteger(branch.ownerResponseCount)} responses captured`,
          tone: "neutral",
        },
      ];

      return `
        <article
          class="branch-card${branch.id === state.focusBranchId ? " is-active" : ""}"
          style="--branch-color: ${escapeHtml(branch.color || "#0d3d7c")}"
          data-branch-card="${escapeHtml(branch.id)}"
          tabindex="0"
          role="button"
          aria-label="Show ${escapeHtml(branch.shortName || branch.name)} spotlight"
        >
          <div class="review-topline branch-card-head">
            <div class="branch-heading">
              <h3 class="branch-title">${escapeHtml(branch.shortName || branch.name)}</h3>
              ${
                branch.id === state.focusBranchId
                  ? `<span class="active-pill">Selected</span>`
                  : ""
              }
            </div>
            <span class="badge">${escapeHtml(branch.location || "")}</span>
          </div>
          <p class="branch-subtitle">${escapeHtml(branch.name)}</p>

          <div class="branch-primary-grid">
            ${primaryStats.map((stat) => `
              <div class="branch-stat-card primary ${escapeHtml(stat.tone)}">
                ${renderMetricLabel(stat.label, "branch-stat-label")}
                <strong class="branch-stat-value">${escapeHtml(stat.value)}</strong>
                <span class="branch-stat-detail">${escapeHtml(stat.detail)}</span>
              </div>
            `).join("")}
          </div>

          <div class="branch-stats-grid">
            ${comparisonStats.map((stat) => `
              <div class="branch-stat-card ${escapeHtml(stat.tone)}">
                ${renderMetricLabel(stat.label, "branch-stat-label")}
                <strong class="branch-stat-value">${escapeHtml(stat.value)}</strong>
                <span class="branch-stat-detail">${escapeHtml(stat.detail)}</span>
              </div>
            `).join("")}
          </div>

          <div class="branch-rating-mix-block">
            ${renderMetricLabel("Ratings mix", "branch-rating-mix-label")}
            <div class="branch-rating-mix">
              ${STAR_LEVELS.map((level) => `
                <span class="rating-mix-chip">${level}★ ${formatInteger(branch.starCounts[level])}</span>
              `).join("")}
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  container.querySelectorAll("[data-branch-card]").forEach((card) => {
    const branchId = card.getAttribute("data-branch-card");
    const activate = () => activateFocusBranch(branchId);

    card.addEventListener("click", activate);
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activate();
      }
    });
  });
}

function renderTrendChart(container, buckets) {
  if (!buckets.length) {
    container.innerHTML = getEmptyState();
    return;
  }

  const maxCount = Math.max(...buckets.map((bucket) => bucket.count), 1);

  container.innerHTML = `
    <div class="bar-group">
      ${buckets
        .map((bucket) => {
          const height = bucket.count ? (bucket.count / maxCount) * 100 : 0;
          const averageLabel = bucket.count ? `${formatRating(bucket.averageRating)} avg` : "No reviews";
          return `
            <div class="bar-column" title="${escapeHtml(
              `${bucket.label}: ${bucket.count} reviews, avg ${formatRating(bucket.averageRating)}`
            )}">
              <div class="bar-rail">
                <div class="bar-fill${bucket.count ? "" : " is-empty"}" style="height: ${height}%"></div>
              </div>
              <div class="bar-meta">
                <strong class="bar-count">${formatInteger(bucket.count)}</strong>
                <span class="bar-label">${escapeHtml(bucket.shortLabel)}</span>
                <span>${escapeHtml(averageLabel)}</span>
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function getFocusBranch(model) {
  return model.branches.find((item) => item.id === state.focusBranchId) || model.branches[0];
}

function renderLeaderboard(model) {
  document.getElementById("leaderboardHead").innerHTML = `
    <tr>
      <th>Rank</th>
      <th class="table-row-label">Branch</th>
      <th>${renderMetricLabel("Rating", "table-metric-label")}</th>
      <th>${renderMetricLabel("Total reviews", "table-metric-label")}</th>
      <th>${renderMetricLabel("Portfolio share", "table-metric-label")}</th>
      <th>Last 30 days</th>
      <th>${renderMetricLabel("30-day rating", "table-metric-label")}</th>
      <th>${renderMetricLabel("Response rate", "table-metric-label")}</th>
    </tr>
  `;

  document.getElementById("leaderboardBody").innerHTML = model.rankedBranches
    .map(
      (branch, index) => `
        <tr>
          <td data-label="Rank"><strong>${index + 1}</strong></td>
          <td class="table-row-label mobile-heading-cell" data-label="Branch">
            <span class="branch-pill">${escapeHtml(branch.shortName || branch.name)}</span>
            <span class="sub-value">${escapeHtml(branch.location || "")}</span>
          </td>
          <td data-label="Rating">
            <strong>${escapeHtml(formatRating(branch.currentRating))}</strong>
            <span class="sub-value">${escapeHtml(renderTextStars(branch.currentRating))}</span>
          </td>
          <td data-label="Total reviews">
            <strong>${formatInteger(branch.currentReviewsCount)}</strong>
            <span class="sub-value">${formatInteger(branch.trackedReviewCount)} tracked</span>
          </td>
          <td data-label="Portfolio share">
            <strong>${escapeHtml(formatPercent(branch.shareOfPortfolio))}</strong>
            <span class="sub-value">Of all branch reviews</span>
          </td>
          <td data-label="Last 30 days">
            <strong>${formatInteger(branch.last30Stats.count)}</strong>
            <span class="sub-value">${formatSignedInteger(branch.volumeDelta30)} vs previous</span>
          </td>
          <td data-label="30-day rating">
            <strong>${escapeHtml(formatRating(branch.last30Stats.averageRating))}</strong>
            <span class="sub-value">${formatSignedDecimal(branch.ratingDelta30)} vs previous</span>
          </td>
          <td data-label="Response rate">
            <strong>${escapeHtml(formatPercent(branch.ownerResponseRate))}</strong>
            <span class="sub-value">${formatInteger(branch.ownerResponseCount)} responded</span>
          </td>
        </tr>
      `
    )
    .join("");
}

function renderDistributionTable(model) {
  const rows = [
    {
      label: "All locations",
      starCounts: model.overall.starCounts,
      rating: model.overall.currentRating,
      reviewsCount: model.overall.totalReviews,
    },
    ...model.branches.map((branch) => ({
      label: branch.shortName || branch.name,
      starCounts: branch.starCounts,
      rating: branch.currentRating,
      reviewsCount: branch.currentReviewsCount,
    })),
  ];

  document.getElementById("distributionHead").innerHTML = `
    <tr>
      <th class="table-row-label">Branch</th>
      ${STAR_LEVELS.map((level) => `<th>${level} stars</th>`).join("")}
      <th>${renderMetricLabel("Average rating", "table-metric-label")}</th>
      <th>${renderMetricLabel("Total reviews", "table-metric-label")}</th>
    </tr>
  `;

  document.getElementById("distributionBody").innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td class="table-row-label mobile-heading-cell" data-label="Branch">
            <span class="branch-pill">${escapeHtml(row.label)}</span>
          </td>
          ${STAR_LEVELS.map(
            (level) => `
              <td data-label="${escapeHtml(`${level} stars`)}">
                <strong>${formatInteger(row.starCounts[level])}</strong>
                <span class="sub-value">${escapeHtml(level.toString())}★ reviews</span>
              </td>
            `
          ).join("")}
          <td data-label="Average rating">
            <strong>${escapeHtml(formatRating(row.rating))}</strong>
            <span class="sub-value">Average score</span>
          </td>
          <td data-label="Total reviews">
            <strong>${formatInteger(row.reviewsCount)}</strong>
            <span class="sub-value">Published reviews</span>
          </td>
        </tr>
      `
    )
    .join("");
}

function renderCalendarTable(type, columns, branches) {
  const headId = type === "week" ? "weeklyTableHead" : "monthlyTableHead";
  const bodyId = type === "week" ? "weeklyTableBody" : "monthlyTableBody";
  const bucketKey = type === "week" ? "weeklyBuckets" : "monthlyBuckets";
  const title = type === "week" ? "Branch" : "Branch";

  document.getElementById(headId).innerHTML = `
    <tr>
      <th class="table-row-label">${title}</th>
      ${columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("")}
      <th>Total</th>
    </tr>
  `;

  document.getElementById(bodyId).innerHTML = branches
    .map((branch) => {
      const buckets = branch[bucketKey];
      const totalCount = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
      const weightedAverage = weightedAverageFromBuckets(buckets);

      return `
        <tr>
          <td class="table-row-label mobile-heading-cell" data-label="Branch">
            <span class="branch-pill">${escapeHtml(branch.shortName || branch.name)}</span>
          </td>
          ${buckets
            .map((bucket) => {
              if (!bucket.count) {
                return `<td data-label="${escapeHtml(bucket.label)}"><span class="cell-empty">-</span></td>`;
              }

              return `
                <td data-label="${escapeHtml(bucket.label)}">
                  <strong>${formatInteger(bucket.count)}</strong>
                  <span class="sub-value">${escapeHtml(formatRating(bucket.averageRating))} avg</span>
                </td>
              `;
            })
            .join("")}
          <td data-label="Total">
            <strong>${formatInteger(totalCount)}</strong>
            <span class="sub-value">${escapeHtml(formatRating(weightedAverage))} avg</span>
          </td>
        </tr>
      `;
    })
    .join("");
}

function renderAttentionList(model) {
  const container = document.getElementById("attentionList");

  if (!model.attentionReviews.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3>No open follow-up items found</h3>
        <p>Every tracked 1 to 3 star review currently shows an owner response.</p>
      </div>
    `;
    return;
  }

  container.innerHTML = model.attentionReviews
    .map((review) => {
      const branch = model.branches.find((item) => item.id === review.branchId);
      const comment = review.comment || review.commentTranslated || "No written comment on this review.";

      return `
        <article class="attention-card">
          <div class="review-topline">
            <h3>${escapeHtml(review.reviewerName || "Anonymous reviewer")}</h3>
            <span class="branch-pill">${escapeHtml(branch?.shortName || review.branchName || "Unknown branch")}</span>
          </div>
          <div class="review-meta">
            <div>${renderStars(review.rating)} ${escapeHtml(formatRating(review.rating))}</div>
            <div class="badge">${escapeHtml(formatDate(review.publishedAt, model.timezone))}</div>
          </div>
          <p class="review-comment">${escapeHtml(comment)}</p>
          <div class="review-footer">
            <span class="sub-value">No owner response captured yet</span>
            ${
              review.reviewUrl
                ? `<a class="review-link" href="${escapeAttribute(review.reviewUrl)}" target="_blank" rel="noreferrer">Open review</a>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function renderReviews() {
  if (!state.data) {
    return;
  }

  const timezone = state.data.meta?.timezone || FALLBACK_TIMEZONE;
  const branches = state.data.branches || [];
  const branchLookup = new Map(branches.map((branch) => [branch.id, branch]));

  const filtered = (state.data.reviews || [])
    .filter((review) => {
      if (state.filters.branchId !== "all" && review.branchId !== state.filters.branchId) {
        return false;
      }

      if (state.filters.rating !== "all" && Number(review.rating) !== Number(state.filters.rating)) {
        return false;
      }

      if (!matchesReviewDateRange(review, state.filters.dateRange, timezone)) {
        return false;
      }

      if (!state.filters.search) {
        return true;
      }

      const haystack = [
        review.reviewerName,
        review.comment,
        review.commentTranslated,
        review.ownerResponseText,
        review.branchName,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return haystack.includes(state.filters.search);
    })
    .sort((left, right) => new Date(right.publishedAt) - new Date(left.publishedAt));

  document.getElementById("reviewsSummary").textContent = `${formatInteger(filtered.length)} review${filtered.length === 1 ? "" : "s"} shown`;

  const list = document.getElementById("reviewList");

  if (!filtered.length) {
    list.innerHTML = getEmptyState();
    return;
  }

  list.innerHTML = filtered
    .map((review) => {
      const branch = branchLookup.get(review.branchId);
      const comment = review.comment || review.commentTranslated || "No written comment on this review.";
      const responseDate = review.ownerResponseDate
        ? ` • ${formatDate(review.ownerResponseDate, timezone)}`
        : "";

      return `
        <article class="review-card">
          <div class="review-topline">
            <h3>${escapeHtml(review.reviewerName || "Anonymous reviewer")}</h3>
            <span class="branch-pill" style="border: 1px solid ${escapeHtml(
              branch?.color || "#0d3d7c"
            )}55">${escapeHtml(branch?.shortName || review.branchName || "Unknown branch")}</span>
          </div>
          <div class="review-meta">
            <div>${renderStars(review.rating)} ${escapeHtml(formatRating(review.rating))}</div>
            <div class="badge">${escapeHtml(formatDate(review.publishedAt, timezone))}</div>
          </div>
          <p class="review-comment">${escapeHtml(comment)}</p>
          ${
            review.ownerResponseText
              ? `
                <div class="owner-response">
                  <strong>Owner response${escapeHtml(responseDate)}</strong>
                  <div>${escapeHtml(review.ownerResponseText)}</div>
                </div>
              `
              : ""
          }
          <div class="review-footer">
            <span class="sub-value">${escapeHtml(review.reviewSource || "Google Business Profile review")}</span>
            ${
              review.reviewUrl
                ? `<a class="review-link" href="${escapeAttribute(review.reviewUrl)}" target="_blank" rel="noreferrer">Open review</a>`
                : ""
            }
          </div>
        </article>
      `;
    })
    .join("");
}

function matchesReviewDateRange(review, dateRange, timezone) {
  if (dateRange === "all") {
    return true;
  }

  const reviewDate = zonedDateOnly(new Date(review.publishedAt), timezone);
  const today = zonedDateOnly(new Date(), timezone);

  if (dateRange === "yesterday") {
    const yesterday = addDays(today, -1);
    return isoDate(reviewDate) === isoDate(yesterday);
  }

  if (dateRange === "last_7_days") {
    return reviewDate >= addDays(today, -6);
  }

  if (dateRange === "last_30_days") {
    return reviewDate >= addDays(today, -29);
  }

  if (dateRange === "this_month") {
    return (
      reviewDate.getUTCFullYear() === today.getUTCFullYear() &&
      reviewDate.getUTCMonth() === today.getUTCMonth()
    );
  }

  return true;
}

function renderFailure(error) {
  document.getElementById("summaryCards").innerHTML = `
    <article class="summary-card">
      <span>Data status</span>
      <strong>Data unavailable</strong>
    </article>
  `;

  [
    "branchCards",
    "weeklyTrend",
    "monthlyTrend",
    "attentionList",
    "reviewList",
  ].forEach((id) => {
    document.getElementById(id).innerHTML = `
      <div class="empty-state">
        <h3>Dashboard data could not be loaded</h3>
        <p>${escapeHtml(error.message)}</p>
      </div>
    `;
  });

  document.getElementById("leaderboardBody").innerHTML = tableMessageRow(error.message, 8);
  document.getElementById("distributionBody").innerHTML = tableMessageRow(error.message, 8);
  document.getElementById("weeklyTableBody").innerHTML = tableMessageRow(error.message, 10);
  document.getElementById("monthlyTableBody").innerHTML = tableMessageRow(error.message, 8);

  document.getElementById("dataMode").textContent = "Unavailable";
  document.getElementById("generatedAt").textContent = "Unavailable";
}

function buildPeriodColumns(type, timezone, columnCount) {
  const now = new Date();
  const zonedNow = zonedDateOnly(now, timezone);
  const columns = [];

  if (type === "week") {
    const currentWeekStart = startOfWeek(zonedNow);

    for (let index = columnCount - 1; index >= 0; index -= 1) {
      const start = addDays(currentWeekStart, index * -7);
      const end = addDays(start, 6);
      columns.push({
        key: isoDate(start),
        label: `${shortDate(start)} to ${shortDate(end)}`,
        shortLabel: shortDate(start),
      });
    }
  } else {
    const currentMonthStart = new Date(Date.UTC(
      zonedNow.getUTCFullYear(),
      zonedNow.getUTCMonth(),
      1
    ));

    for (let index = columnCount - 1; index >= 0; index -= 1) {
      const start = new Date(Date.UTC(
        currentMonthStart.getUTCFullYear(),
        currentMonthStart.getUTCMonth() - index,
        1
      ));

      columns.push({
        key: `${start.getUTCFullYear()}-${String(start.getUTCMonth() + 1).padStart(2, "0")}`,
        label: start.toLocaleString("en-US", {
          month: "short",
          year: "numeric",
          timeZone: "UTC",
        }),
        shortLabel: start.toLocaleString("en-US", {
          month: "short",
          timeZone: "UTC",
        }),
      });
    }
  }

  return columns;
}

function bucketReviews(reviews, columns, type, timezone) {
  const buckets = new Map(
    columns.map((column) => [column.key, { ...column, count: 0, ratingSum: 0, averageRating: 0 }])
  );

  reviews.forEach((review) => {
    const key = type === "week"
      ? isoDate(startOfWeek(zonedDateOnly(new Date(review.publishedAt), timezone)))
      : monthKey(zonedDateOnly(new Date(review.publishedAt), timezone));

    if (!buckets.has(key)) {
      return;
    }

    const bucket = buckets.get(key);
    bucket.count += 1;
    bucket.ratingSum += Number(review.rating) || 0;
    bucket.averageRating = bucket.count ? bucket.ratingSum / bucket.count : 0;
  });

  return columns.map((column) => buckets.get(column.key));
}

function computeStarCounts(reviews) {
  const counts = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0 };

  reviews.forEach((review) => {
    const rating = clamp(Number(review.rating) || 0, 1, 5);
    if (counts[rating] !== undefined) {
      counts[rating] += 1;
    }
  });

  return counts;
}

function periodStats(reviews, offsetDays, durationDays) {
  const now = Date.now();
  const periodEnd = now - offsetDays * 24 * 60 * 60 * 1000;
  const periodStart = periodEnd - durationDays * 24 * 60 * 60 * 1000;
  const inPeriod = reviews.filter((review) => {
    const publishedAt = new Date(review.publishedAt).getTime();
    return publishedAt >= periodStart && publishedAt < periodEnd;
  });

  return {
    count: inPeriod.length,
    averageRating: average(inPeriod.map((review) => Number(review.rating) || 0)),
  };
}

function compareBranchPerformance(left, right) {
  return (
    right.currentRating - left.currentRating ||
    right.last30Stats.count - left.last30Stats.count ||
    right.currentReviewsCount - left.currentReviewsCount
  );
}

function weightedAverageFromBuckets(buckets) {
  const totalCount = buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  const weightedSum = buckets.reduce((sum, bucket) => sum + bucket.averageRating * bucket.count, 0);
  return totalCount ? weightedSum / totalCount : 0;
}

function countSince(reviews, days) {
  const threshold = Date.now() - days * 24 * 60 * 60 * 1000;
  return reviews.filter((review) => new Date(review.publishedAt).getTime() >= threshold).length;
}

function countMatchingSince(reviews, days, predicate) {
  const threshold = Date.now() - days * 24 * 60 * 60 * 1000;
  return reviews.filter((review) => (
    new Date(review.publishedAt).getTime() >= threshold && predicate(review)
  )).length;
}

function countCurrentMonth(reviews, timezone) {
  const now = zonedDateOnly(new Date(), timezone);
  return reviews.filter((review) => {
    const reviewDate = zonedDateOnly(new Date(review.publishedAt), timezone);
    return (
      reviewDate.getUTCFullYear() === now.getUTCFullYear() &&
      reviewDate.getUTCMonth() === now.getUTCMonth()
    );
  }).length;
}

function estimateFiveStarReviewsForLift(currentRating, reviewCount, increase = 0.1) {
  const rating = Number(currentRating) || 0;
  const count = Number(reviewCount) || 0;

  if (!rating || !count || rating >= 4.95) {
    return 0;
  }

  const target = Math.min(5, roundToOneDecimal(rating + increase));
  const numerator = count * (target - rating);
  const denominator = 5 - target;

  if (denominator <= 0) {
    return 0;
  }

  return Math.max(0, Math.ceil(numerator / denominator));
}

function estimateOneStarImpact(currentRating, reviewCount, oneStarCount) {
  const rating = Number(currentRating) || 0;
  const count = Number(reviewCount) || 0;
  const oneStars = Number(oneStarCount) || 0;

  if (!rating || !count || !oneStars || count <= oneStars) {
    return 0;
  }

  const ratingWithoutRecentOneStars = ((rating * count) - oneStars) / (count - oneStars);
  return rating - ratingWithoutRecentOneStars;
}

function average(values) {
  const validValues = values.filter((value) => Number(value) > 0);

  if (!validValues.length) {
    return 0;
  }

  return validValues.reduce((sum, value) => sum + value, 0) / validValues.length;
}

function formatInteger(value) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 0,
  }).format(Number(value) || 0);
}

function formatRating(value) {
  if (!Number.isFinite(Number(value)) || Number(value) <= 0) {
    return "0.0";
  }

  return (Math.round(Number(value) * 10) / 10).toFixed(1);
}

function formatPercent(value) {
  return `${Math.round((Number(value) || 0) * 10) / 10}%`;
}

function formatSignedInteger(value) {
  const number = Number(value) || 0;
  if (number > 0) {
    return `+${formatInteger(number)}`;
  }
  return number < 0 ? `-${formatInteger(Math.abs(number))}` : "0";
}

function formatSignedDecimal(value) {
  const number = Number(value) || 0;
  if (number > 0) {
    return `+${formatPreciseDecimal(number)}`;
  }
  return number < 0 ? `-${formatPreciseDecimal(Math.abs(number))}` : "0.00";
}

function formatDate(value, timezone) {
  if (!value) {
    return "No date";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatDateTime(value, timezone) {
  if (!value) {
    return "Unavailable";
  }

  return new Intl.DateTimeFormat("en-GB", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatPreciseDecimal(value) {
  if (!Number.isFinite(Number(value))) {
    return "0.00";
  }

  return Number(value).toFixed(2);
}

function renderStars(value) {
  const rounded = clamp(Math.round(Number(value) || 0), 0, 5);
  return `<span class="stars-line" aria-label="${rounded} stars">${"★".repeat(rounded)}${"☆".repeat(5 - rounded)}</span>`;
}

function renderTextStars(value) {
  const rounded = clamp(Math.round(Number(value) || 0), 0, 5);
  return `${"★".repeat(rounded)}${"☆".repeat(5 - rounded)}`;
}

function zonedDateOnly(date, timezone) {
  const formatter = new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });

  const parts = Object.fromEntries(
    formatter
      .formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value])
  );

  return new Date(Date.UTC(Number(parts.year), Number(parts.month) - 1, Number(parts.day)));
}

function startOfWeek(date) {
  const day = date.getUTCDay() || 7;
  return addDays(date, 1 - day);
}

function addDays(date, days) {
  const clone = new Date(date.getTime());
  clone.setUTCDate(clone.getUTCDate() + days);
  return clone;
}

function isoDate(date) {
  return date.toISOString().slice(0, 10);
}

function monthKey(date) {
  return `${date.getUTCFullYear()}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function shortDate(date) {
  return date.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function roundToOneDecimal(value) {
  return Math.round(Number(value) * 10) / 10;
}

function isFiniteNumber(value) {
  return Number.isFinite(Number(value));
}

function normalizeMatchText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replaceAll("&", "and")
    .replace(/[^a-z0-9\s-]/g, " ")
    .replaceAll("-", " ")
    .replace(/\s+/g, " ")
    .trim();
}

function normalizeMatchToken(value) {
  return String(value ?? "").trim();
}

function percentage(part, total) {
  if (!total) {
    return 0;
  }

  return (Number(part) / Number(total)) * 100;
}

function hasWrittenComment(review) {
  return Boolean((review.comment || review.commentTranslated || "").trim());
}

function hasOwnerResponse(review) {
  return Boolean((review.ownerResponseText || "").trim());
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function escapeAttribute(value) {
  return escapeHtml(value);
}

function tableMessageRow(message, colspan) {
  return `
    <tr>
      <td colspan="${colspan}">
        <div class="empty-state">
          <h3>Dashboard data could not be loaded</h3>
          <p>${escapeHtml(message)}</p>
        </div>
      </td>
    </tr>
  `;
}

function getEmptyState() {
  return document.getElementById("emptyStateTemplate").innerHTML;
}
