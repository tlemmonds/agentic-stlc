---
helper: true
title: "Navigate to the shopping cart page"
description: "Open the /checkout/cart page in the current tab."
variables:
  base_url:
    value: "https://ecommerce-playground.lambdatest.io"
    secret: false
---

# Helper — Open the shopping cart page

> Used by remove-item and update-quantity scenarios after the cart has
> been populated.

## Step 1 — Navigate to /checkout/cart

Open `{{base_url}}/index.php?route=checkout/cart` in the current browser tab
and wait for the cart line items to render.
