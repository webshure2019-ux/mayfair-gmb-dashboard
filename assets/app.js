const FALLBACK_TIMEZONE = "Africa/Johannesburg";
const STAR_LEVELS = [5, 4, 3, 2, 1];
const WEEK_COLUMNS = 8;
const MONTH_COLUMNS = 6;

const state = {
  data: null,
  filters: {
    branchId: "all",
    rating: "all",
    search: "",
  },
};

document.addEventListener("DOMContentLoaded", async () => {
  hydrateBrandImages();
  wireFilters();

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

    img.addEventListener("load", () => {
      if (img.naturalWidth > 0) {
        frame.classList.add("has-image");
      }
    });

    img.addEventListener("error", () => {
      frame.classList.remove("has-image");
    });
  });
}

function wireFilters() {
  document.getElementById("branchFilter").addEventListener("change", (event) => {
    state.filters.branchId = event.target.value;
    renderReviews();
  });

  document.getElementById("ratingFilter").addEventListener("change", (event) => {
    state.filters.rating = event.target.value;
    renderReviews();
  });

  document.getElementById("searchFilter").addEventListener("input", (event) => {
    state.filters.search = event.target.value.trim().toLowerCase();
    renderReviews();
  });
}

function renderDashboard() {
  const data = state.data;
  const timezone = data.meta?.timezone || FALLBACK_TIMEZONE;
  const computed = buildComputedModel(data, timezone);

  state.computed = computed;
  populateHeader(data, timezone);
  populateBranchFilter(computed.branches);
  renderSummaryCards(computed);
  renderInsightCards(computed);
  renderKeywordCloud(computed.keywordThemes);
  renderBranchCards(computed.branches);
  renderTrendChart(document.getElementById("weeklyTrend"), computed.weeklyTotals);
  renderTrendChart(document.getElementById("monthlyTrend"), computed.monthlyTotals);
  renderLeaderboard(computed);
  renderDistributionTable(computed);
  renderCalendarTable("week", computed.weeklyColumns, computed.branches);
  renderCalendarTable("month", computed.monthlyColumns, computed.branches);
  renderAttentionList(computed);
  renderReviews();
}

function repairDashboardData(data) {
  const branches = (data.branches || []).map((branch) => ({ ...branch }));
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
    branch.last30Stats = periodStats(branch.reviews, 0, 30);
    branch.previous30Stats = periodStats(branch.reviews, 30, 30);
    branch.ratingDelta30 = branch.last30Stats.averageRating - branch.previous30Stats.averageRating;
    branch.volumeDelta30 = branch.last30Stats.count - branch.previous30Stats.count;
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
  const keywordThemes = extractKeywordThemes(reviews);
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
    keywordThemes,
    attentionReviews,
    highlights: buildHighlights(branches),
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

function populateBranchFilter(branches) {
  const branchFilter = document.getElementById("branchFilter");

  branchFilter.innerHTML = [
    `<option value="all">All branches</option>`,
    ...branches.map(
      (branch) =>
        `<option value="${escapeHtml(branch.id)}">${escapeHtml(branch.shortName || branch.name)}</option>`
    ),
  ].join("");
}

function renderSummaryCards(model) {
  const cards = [
    {
      label: "Total reviews",
      value: formatInteger(model.overall.totalReviews),
    },
    {
      label: "Current rating",
      value: formatRating(model.overall.currentRating),
    },
    {
      label: "Reviews in last 30 days",
      value: formatInteger(model.overall.reviewsLast30Days),
    },
    {
      label: "30-day rating",
      value: formatRating(model.overall.last30Stats.averageRating),
    },
    {
      label: "Owner response rate",
      value: formatPercent(model.overall.ownerResponseRate),
    },
    {
      label: "Written comment rate",
      value: formatPercent(model.overall.commentRate),
    },
    {
      label: "Local guide share",
      value: formatPercent(model.overall.localGuideShare),
    },
    {
      label: "1-2 star share",
      value: formatPercent(model.overall.lowStarShare),
    },
  ];

  document.getElementById("summaryCards").innerHTML = cards
    .map(
      (card) => `
        <article class="summary-card">
          <span>${escapeHtml(card.label)}</span>
          <strong>${escapeHtml(card.value)}</strong>
        </article>
      `
    )
    .join("");
}

function renderInsightCards(model) {
  const highlights = model.highlights;
  const cards = [
    {
      title: "Best rated branch",
      value: highlights.bestRated?.shortName || "N/A",
      detail: highlights.bestRated
        ? `${formatRating(highlights.bestRated.currentRating)} rating across ${formatInteger(highlights.bestRated.currentReviewsCount)} reviews`
        : "No branch data yet",
    },
    {
      title: "Most review volume",
      value: highlights.mostReviewed?.shortName || "N/A",
      detail: highlights.mostReviewed
        ? `${formatInteger(highlights.mostReviewed.currentReviewsCount)} total reviews`
        : "No branch data yet",
    },
    {
      title: "Fastest 30-day momentum",
      value: highlights.fastestMomentum?.shortName || "N/A",
      detail: highlights.fastestMomentum
        ? `${formatSignedInteger(highlights.fastestMomentum.volumeDelta30)} reviews vs previous 30 days`
        : "No branch data yet",
    },
    {
      title: "Needs attention most",
      value: highlights.needsAttention?.shortName || "N/A",
      detail: highlights.needsAttention
        ? `${formatPercent(highlights.needsAttention.lowStarShare)} of tracked reviews are 1-2 stars`
        : "No branch data yet",
    },
  ];

  document.getElementById("insightCards").innerHTML = cards
    .map(
      (card) => `
        <article class="insight-card">
          <span>${escapeHtml(card.title)}</span>
          <strong>${escapeHtml(card.value)}</strong>
          <p>${escapeHtml(card.detail)}</p>
        </article>
      `
    )
    .join("");
}

function renderKeywordCloud(keywords) {
  const container = document.getElementById("keywordCloud");

  if (!keywords.length) {
    container.innerHTML = getEmptyState();
    return;
  }

  container.innerHTML = keywords
    .map((keyword) => `
      <div class="keyword-chip">
        <strong>${escapeHtml(keyword.term)}</strong>
        <span>${formatInteger(keyword.count)} mentions</span>
      </div>
    `)
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
      const stars = STAR_LEVELS.map(
        (level) => `${level}★ ${formatInteger(branch.starCounts[level])}`
      ).join(" · ");

      return `
        <article class="branch-card" style="--branch-color: ${escapeHtml(branch.color || "#ff8f3d")}">
          <div class="review-topline">
            <h3 class="branch-title">${escapeHtml(branch.shortName || branch.name)}</h3>
            <span class="badge">${escapeHtml(branch.location || "")}</span>
          </div>
          <p class="branch-subtitle">${escapeHtml(branch.name)}</p>

          <div class="metric-row">
            <span>Current rating</span>
            <strong>${renderStars(branch.currentRating)} ${escapeHtml(formatRating(branch.currentRating))}</strong>
          </div>
          <div class="metric-row">
            <span>Total reviews</span>
            <strong>${formatInteger(branch.currentReviewsCount)}</strong>
          </div>
          <div class="metric-row">
            <span>Last 7 days</span>
            <strong>${formatInteger(branch.thisWeekCount)}</strong>
          </div>
          <div class="metric-row">
            <span>Last 30 days</span>
            <strong>${formatInteger(branch.thisMonthCount)}</strong>
          </div>
          <div class="metric-row">
            <span>Owner response rate</span>
            <strong>${escapeHtml(formatPercent(branch.ownerResponseRate))}</strong>
          </div>
          <div class="metric-row">
            <span>1-2 star share</span>
            <strong>${escapeHtml(formatPercent(branch.lowStarShare))}</strong>
          </div>
          <div class="metric-row">
            <span>Star mix</span>
            <strong>${escapeHtml(stars)}</strong>
          </div>
        </article>
      `;
    })
    .join("");
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
          const height = Math.max(10, (bucket.count / maxCount) * 100);
          return `
            <div class="bar-column" title="${escapeHtml(
              `${bucket.label}: ${bucket.count} reviews, avg ${formatRating(bucket.averageRating)}`
            )}">
              <div class="bar-rail">
                <div class="bar-fill" data-value="${bucket.count}" style="height: ${height}%"></div>
              </div>
              <div class="bar-meta">
                <strong>${escapeHtml(bucket.shortLabel)}</strong>
                <span>${escapeHtml(formatRating(bucket.averageRating))} avg</span>
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderLeaderboard(model) {
  document.getElementById("leaderboardHead").innerHTML = `
    <tr>
      <th>Rank</th>
      <th class="table-row-label">Branch</th>
      <th>Rating</th>
      <th>Total reviews</th>
      <th>Portfolio share</th>
      <th>Last 30 days</th>
      <th>30-day rating</th>
      <th>Response rate</th>
      <th>1-2 star share</th>
    </tr>
  `;

  document.getElementById("leaderboardBody").innerHTML = model.rankedBranches
    .map(
      (branch, index) => `
        <tr>
          <td><strong>${index + 1}</strong></td>
          <td class="table-row-label">
            <span class="branch-pill">${escapeHtml(branch.shortName || branch.name)}</span>
            <span class="sub-value">${escapeHtml(branch.location || "")}</span>
          </td>
          <td>
            <strong>${escapeHtml(formatRating(branch.currentRating))}</strong>
            <span class="sub-value">${escapeHtml(renderTextStars(branch.currentRating))}</span>
          </td>
          <td>
            <strong>${formatInteger(branch.currentReviewsCount)}</strong>
            <span class="sub-value">${formatInteger(branch.trackedReviewCount)} tracked</span>
          </td>
          <td>
            <strong>${escapeHtml(formatPercent(branch.shareOfPortfolio))}</strong>
            <span class="sub-value">Of all branch reviews</span>
          </td>
          <td>
            <strong>${formatInteger(branch.last30Stats.count)}</strong>
            <span class="sub-value">${formatSignedInteger(branch.volumeDelta30)} vs previous</span>
          </td>
          <td>
            <strong>${escapeHtml(formatRating(branch.last30Stats.averageRating))}</strong>
            <span class="sub-value">${formatSignedDecimal(branch.ratingDelta30)} vs previous</span>
          </td>
          <td>
            <strong>${escapeHtml(formatPercent(branch.ownerResponseRate))}</strong>
            <span class="sub-value">${formatInteger(branch.ownerResponseCount)} responded</span>
          </td>
          <td>
            <strong>${escapeHtml(formatPercent(branch.lowStarShare))}</strong>
            <span class="sub-value">${formatInteger(branch.lowStarCount)} low-star</span>
          </td>
        </tr>
      `
    )
    .join("");
}

function renderDistributionTable(model) {
  const rows = [
    {
      label: "All branches",
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
      <th>Current rating</th>
      <th>Total reviews</th>
    </tr>
  `;

  document.getElementById("distributionBody").innerHTML = rows
    .map(
      (row) => `
        <tr>
          <td class="table-row-label">${escapeHtml(row.label)}</td>
          ${STAR_LEVELS.map(
            (level) => `
              <td>
                <strong>${formatInteger(row.starCounts[level])}</strong>
                <span class="sub-value">${escapeHtml(level.toString())}★ reviews</span>
              </td>
            `
          ).join("")}
          <td>
            <strong>${escapeHtml(formatRating(row.rating))}</strong>
            <span class="sub-value">Average score</span>
          </td>
          <td>
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
          <td class="table-row-label">
            <span class="branch-pill">${escapeHtml(branch.shortName || branch.name)}</span>
          </td>
          ${buckets
            .map((bucket) => {
              if (!bucket.count) {
                return `<td><span class="cell-empty">-</span></td>`;
              }

              return `
                <td>
                  <strong>${formatInteger(bucket.count)}</strong>
                  <span class="sub-value">${escapeHtml(formatRating(bucket.averageRating))} avg</span>
                </td>
              `;
            })
            .join("")}
          <td>
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
        <h3>No unanswered low-rated reviews found</h3>
        <p>Every 1 to 3 star tracked review currently shows an owner response.</p>
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
              branch?.color || "#ff8f3d"
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

function renderFailure(error) {
  document.getElementById("summaryCards").innerHTML = `
    <article class="summary-card">
      <span>Dashboard status</span>
      <strong>Data unavailable</strong>
    </article>
  `;

  [
    "insightCards",
    "keywordCloud",
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

  document.getElementById("leaderboardBody").innerHTML = tableMessageRow(error.message, 9);
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

function buildHighlights(branches) {
  if (!branches.length) {
    return {};
  }

  return {
    bestRated: [...branches].sort((left, right) => (
      right.currentRating - left.currentRating ||
      right.currentReviewsCount - left.currentReviewsCount
    ))[0],
    mostReviewed: [...branches].sort((left, right) => right.currentReviewsCount - left.currentReviewsCount)[0],
    fastestMomentum: [...branches].sort((left, right) => (
      right.volumeDelta30 - left.volumeDelta30 ||
      right.last30Stats.count - left.last30Stats.count
    ))[0],
    needsAttention: [...branches].sort((left, right) => (
      right.lowStarShare - left.lowStarShare ||
      right.lowStarCount - left.lowStarCount
    ))[0],
  };
}

function compareBranchPerformance(left, right) {
  return (
    right.currentRating - left.currentRating ||
    right.last30Stats.count - left.last30Stats.count ||
    right.currentReviewsCount - left.currentReviewsCount
  );
}

function extractKeywordThemes(reviews) {
  const stopwords = new Set([
    "about", "again", "after", "all", "also", "and", "are", "back", "because", "been",
    "before", "but", "can", "car", "centre", "communication", "did", "done", "drives",
    "even", "excellent", "fair", "for", "from", "gearbox", "good", "great", "had",
    "has", "have", "helpful", "honest", "issue", "its", "job", "just", "like", "manual",
    "more", "much", "need", "not", "now", "our", "overall", "really", "repair", "repaired",
    "service", "sorted", "staff", "team", "than", "that", "the", "their", "them", "they",
    "this", "throughout", "truck", "very", "vehicle", "was", "were", "what", "with", "work",
    "workshop", "would", "you", "your",
  ]);

  const counts = new Map();

  reviews.forEach((review) => {
    const text = (review.comment || review.commentTranslated || "")
      .toLowerCase()
      .replace(/[^a-z0-9\s]/g, " ");

    const uniqueTerms = new Set(
      text
        .split(/\s+/)
        .map((term) => term.trim())
        .filter((term) => term.length >= 4 && !stopwords.has(term))
    );

    uniqueTerms.forEach((term) => {
      counts.set(term, (counts.get(term) || 0) + 1);
    });
  });

  return [...counts.entries()]
    .map(([term, count]) => ({ term, count }))
    .sort((left, right) => right.count - left.count || left.term.localeCompare(right.term))
    .slice(0, 12);
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
    return `+${formatRating(number)}`;
  }
  return number < 0 ? `-${formatRating(Math.abs(number))}` : "0.0";
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
