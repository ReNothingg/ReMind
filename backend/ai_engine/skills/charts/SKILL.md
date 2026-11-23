# Charts

Display data charts using the existing Chart.js or D3 renderer.

Call `render_widget` with format `chartjs` or `d3js` and a JSON string in `content`. For Chart.js include a supported chart type and a data object with labels and datasets. Use measured or explicitly labelled synthetic values. Include units and accessible labels; avoid ambiguous or misleading axes. Use Python for computed results and exportable figures when requested. Do not claim a rendered chart until the tool succeeds.
