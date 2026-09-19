# Demo image generator

Produce an internal diagnostic image to verify the image delivery flow.

Use `generate_demo_image` only when a test image is useful or explicitly requested. This is not a generative art model and does not produce production-quality assets or edit an uploaded image. Explain that limitation if the user requests professional visual assets. Do not describe the diagnostic output as a completed design deliverable. The function is restricted to accounts allowed to use the internal Image model and requires a persistent chat. It returns the actual image URLs and a demo flag; never invent a download URL.
