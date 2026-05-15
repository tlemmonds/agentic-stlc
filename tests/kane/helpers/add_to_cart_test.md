---
helper: true
title: "Add the canonical product to the shopping cart"
description: "Open product 47 (HP LP3065) and click Add to Cart, confirming the cart count increments."
---

@import ../helpers/open_product_test.md

# Helper — Add canonical product to cart

> Reusable building block for any flow that needs a populated cart
> (remove-item, update-qty, guest-checkout). Imports `open_product_test.md`
> so the canonical-product choice stays in one place.

## Step 1 — Read the cart counter

Note the current text shown in the cart button at the top-right of the page
(it typically reads `0 item(s) - $0.00`). Remember this value.

## Step 2 — Click Add to Cart

Click the **Add to Cart** button in the product purchase panel.

## Step 3 — Confirm the cart updated

Wait for the cart button text to change to a value different from the value
you noted in Step 1 — it should now reflect at least one item and a
non-zero subtotal. Do not stop until this confirmation is visible.
