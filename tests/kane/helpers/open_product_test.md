---
helper: true
title: "Open the canonical in-stock product detail page"
description: "Navigate to the HP LP3065 product (id=47): in-stock, no required options."
variables:
  product_id:
    value: "47"
    secret: false
  base_url:
    value: "https://ecommerce-playground.lambdatest.io"
    secret: false
---

# Helper — Open canonical product detail page

> Imported by cart, wishlist and checkout scenarios that need a known-good
> product whose Add-to-Cart button works without selecting an option.
> Centralizing the choice here means an inventory shift on the AUT only
> requires editing one file.

## Step 1 — Navigate

Open `{{base_url}}/index.php?route=product/product&product_id={{product_id}}`
in the current browser tab. Wait for the product detail page to render the
product name and the **Add to Cart** button.
