# Visualization Use Cases

Use the smallest chart that answers the question. The choices below are defaults, not overrides
of an explicit user request.

| Analytical question | Default view | Important choices |
|---|---|---|
| How does a value change over time? | Line chart | Use a real datetime axis, consistent time grain, and one line per meaningful series. Use an area chart only when magnitude or accumulation matters. |
| Which category is larger? | Sorted bar chart | Horizontal bars work best for long labels. Aggregate repeated categories and start the value axis at zero. |
| What is the distribution? | Histogram | Choose interpretable bins. Add a box or violin plot when group comparison matters; use KDE only when smoothing is appropriate. |
| Are two numeric variables related? | Scatter plot | Add color for a third meaningful dimension. Use transparency, hex bins, or Datashader as overlap increases. |
| How do groups compare across time? | Multi-line or faceted line chart | Prefer facets when lines overlap or there are many groups. Avoid unreadable legends. |
| What contributes to a total? | Stacked bar or area chart | Use only when totals and components both matter. Use small multiples when precise component comparison matters more. |
| What is the rank? | Sorted bar or dot plot | Show the requested top or bottom subset and disclose the filter. |
| Where are values located? | GeoViews or deck.gl map | Use points for events, choropleths for normalized regional rates, and Datashader for dense coordinates. Never map raw counts when region sizes make them misleading. |
| How are many numeric dimensions related? | HoloViews linked views, scatter matrix, or faceted plots | Select dimensions relevant to the question. Use color and size sparingly and provide hover details. |
| How does a matrix vary? | Heatmap | Order rows and columns meaningfully and use a perceptually appropriate sequential or diverging palette. |
| How do items move between stages? | Sankey or flow diagram | Use only when flow magnitude is the question; otherwise a table or bar chart is clearer. |
| What is nested inside what? | Treemap or sunburst | Use for hierarchy overview, not precise comparisons. Provide labels and hover values. |
| What are the current KPIs? | Panel dashboard | Lead with a few indicators, then supporting trends and filters. Keep controls close to the views they affect. |

## Automatic fallback

When the user supplies data without a specific analytical question:

1. With categorical and numeric columns, show an aggregated bar chart.
2. With two numeric columns, show a scatter plot.
3. With one numeric column, show its value over row order; use a histogram when the request is
   explicitly about distribution.
4. With only categorical columns, show counts for the lowest-cardinality useful column.
5. With three or more numeric columns, use HoloViews to encode a third dimension with color and
   keep the remaining dimensions available for follow-up views.
