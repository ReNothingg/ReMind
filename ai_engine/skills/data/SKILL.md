# Data

Inspect, filter, sort and summarize CSV files and flat JSON arrays of objects without executing code.

Start with `table_inspect` for exact column names, numeric ranges, missing cells and sample rows. Use `table_query` for literal filters, numeric greater/less comparisons, column selection, pagination, sorting and grouped count/sum/average/min/max. Values are parsed conservatively: numeric aggregation ignores empty and non-numeric cells; currencies, localized decimals and dates are not inferred. Explain this if it affects the result. Ungrouped aggregation is not supported; use Python for custom analysis.

Inputs are limited to 20,000 rows, 128 columns and the file-reading byte limit. Results contain bounded cell previews; optional CSV export includes every matched row, not just the displayed page. Export is available only in persistent signed-in chats. Dangerous spreadsheet formula prefixes are escaped in exported CSV; the tool reports when this happened. All filenames come from `file_list`. Never invent a table, statistics, file or successful export.

A query selects at most 32 columns at once (the first 32 by default). `columns_truncated` reports this. Specify the exact columns when inspecting a wide table; use isolated Python when an export must include more columns. Samples and displayed cell strings are shortened; CSV exports preserve the selected columns and full cell values except reported formula escaping.
