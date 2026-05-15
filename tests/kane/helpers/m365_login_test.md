---
helper: true
title: "Sign into Microsoft 365 for Power Apps scenarios"
description: "Reusable Microsoft 365 / Power Apps login flow. Reads {{m365_username}} and {{m365_password}} from variables (push as secrets in CI)."
variables:
  m365_username:
    value: ""
    secret: true
  m365_password:
    value: ""
    secret: true
  power_apps_url:
    value: "https://make.powerapps.com/"
    secret: false
---

# Helper — Microsoft 365 / Power Apps login

> Imported by Power Apps scenarios that require an authenticated session.
> Credentials must be supplied via Kane secret variables — never hardcode
> values in this file.

## Step 1 — Open Power Apps

Open `{{power_apps_url}}` in the current browser tab.

## Step 2 — Enter the email address

When the Microsoft sign-in page renders, type `{{m365_username}}` into the
email field and click **Next**.

## Step 3 — Enter the password

When the password page renders, type `{{m365_password}}` into the password
field and click **Sign in**.

## Step 4 — Dismiss "Stay signed in?"

If a "Stay signed in?" prompt appears, click **No**.

## Step 5 — Confirm the Power Apps home loads

Wait until the Power Apps home page renders the left navigation rail and
the page heading **Apps** or **Home** is visible.
