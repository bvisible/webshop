# Webshop Core Templates Documentation

This guide documents the core template includes for the Frappe Webshop, detailing their purpose, required context variables, optional parameters, usage examples, and dependencies.

## Table of Contents
1. [Brand Carousel](#brand-carousel)
2. [Cart Component](#cart-component)
3. [Mobile Menu](#mobile-menu)
4. [Product Carousel](#product-carousel)
5. [Search Box](#search-box)
6. [User Header](#user-header)
7. [Wishlist Component](#wishlist-component)

---

## Brand Carousel

**File:** `/webshop/templates/includes/brand_carousel.html`

### Purpose and Functionality
The brand carousel displays a responsive, interactive carousel of brand logos and information. It features:
- Auto-rotating brand display
- Touch/swipe support for mobile devices
- Responsive layout (1-4 items per view based on screen size)
- Hover effects with "View Products" button
- Navigation arrows and dot indicators
- Brand logo display with fallback to initials

### Required Context Variables
- `brands` (list): Array of brand objects. Each brand object should contain:
  - `route` (string): URL path to the brand page
  - `brand_name` (string): Display name of the brand
  - `logo` (string, optional): URL to the brand logo image
  - `description` (string, optional): Brand description text

### Optional Parameters/Variables
- `carousel_id` (string): Custom ID for the carousel element (default: 'brand-carousel')
- `carousel_title` (string): Title to display above the carousel

### Example Usage
```html
{% include "webshop/templates/includes/brand_carousel.html" %}

<!-- With custom parameters -->
{% set brands = [
  {
    "route": "brands/nike",
    "brand_name": "Nike",
    "logo": "/files/nike-logo.png",
    "description": "Just Do It - Leading sportswear brand"
  },
  {
    "route": "brands/adidas",
    "brand_name": "Adidas",
    "logo": "/files/adidas-logo.png",
    "description": "Impossible is Nothing"
  }
] %}

{% include "webshop/templates/includes/brand_carousel.html" with context %}

<!-- With custom title and ID -->
{% set carousel_title = "Featured Brands" %}
{% set carousel_id = "featured-brands-carousel" %}
{% include "webshop/templates/includes/brand_carousel.html" with context %}
```

### Dependencies
- **CSS:** Embedded within the template
- **JavaScript:** Self-contained carousel logic with:
  - Touch/swipe event handling
  - Responsive breakpoint handling
  - Auto-play functionality (5-second intervals)
  - Navigation controls

---

## Cart Component

**File:** `/webshop/templates/includes/cart_component.html`

### Purpose and Functionality
The cart component provides a comprehensive shopping cart interface including:
- Slide-out cart drawer with overlay
- Real-time cart item display with quantities
- Tax and subtotal calculations
- Loyalty points display (if enabled)
- Quick links to full cart and checkout pages
- Cart badge with item count

### Required Context Variables
The component calls `get_cart_data()` internally which provides:
- `cart_info` (dict): General cart information
- `cart_items` (list): Array of cart items
- `cart_items_count` (int): Total number of items
- `cart_total` (string): Formatted total amount
- `currency` (string): Currency code
- `tax_info` (dict): Tax breakdown information
- `loyalty_info` (dict): Loyalty points information
- `show_loyalty` (bool): Whether to show loyalty points
- `show_loyalty_for_guests` (bool): Show loyalty for guest users

### Optional Parameters/Variables
None - the component is self-contained and uses Webshop Settings for configuration.

### Example Usage
```html
<!-- Basic inclusion (exclude from cart and checkout pages) -->
{% include "webshop/templates/includes/cart_component.html" %}

<!-- Component automatically excludes itself from /cart and /checkout pages -->
```

### Dependencies
- **CSS:** `webshop/templates/includes/cart_component.css` (included inline)
- **JavaScript:** 
  - `webshop/templates/includes/cart_component.js` (included inline)
  - `webshop/public/js/utils/frappe-mock.js` (included inline)
- **Server-side:** 
  - `get_cart_data()` function
  - Webshop Settings doctype for loyalty configuration

---

## Mobile Menu

**File:** `/webshop/templates/includes/mobile_menu.html`

### Purpose and Functionality
The mobile menu provides a responsive navigation system for mobile devices featuring:
- Hamburger menu toggle button
- Slide-in menu drawer from the right
- Dynamic relocation of authentication component for mobile view
- Navigation content loaded from server
- Overlay background when menu is open
- Automatic close on link click or overlay click

### Required Context Variables
None - the component fetches navigation content dynamically via:
```python
frappe.call("webshop.webshop.utils.mobile_menu.get_navigation_content", route="navbar", use_cache=True)
```

### Optional Parameters/Variables
None - the component is fully self-contained.

### Example Usage
```html
<!-- Basic inclusion -->
{% include "webshop/templates/includes/mobile_menu.html" %}

<!-- The component will automatically show/hide based on parent visibility -->
```

### Dependencies
- **CSS:** Embedded within the template
- **JavaScript:** Self-contained with:
  - Menu toggle functionality
  - Dynamic header authentication relocation
  - Responsive behavior monitoring
  - MutationObserver for parent visibility changes
- **Server-side:** `webshop.webshop.utils.mobile_menu.get_navigation_content` method

---

## Product Carousel

**File:** `/webshop/templates/includes/product_carousel.html`

### Purpose and Functionality
The product carousel displays a responsive, interactive carousel of products with:
- Product images with hover zoom effect
- Product name, description, and pricing
- Discount display with strikethrough original price
- "Discover" button on hover
- Touch/swipe support
- Auto-play with pause on hover
- Responsive layout (1-4 products per view)

### Required Context Variables
- `website_items` (list): Array of product objects. Each item should contain:
  - `route` (string): URL path to the product page
  - `web_item_name` or `item_name` or `name` (string): Product display name
  - `website_image` (string, optional): Product image URL
  - `abbr` (string): Abbreviation for no-image fallback
  - `description` (string, optional): Product description
  - `price` (float, optional): Current price
  - `formatted_price` (string): Formatted price string
  - `formatted_mrp` (string, optional): Formatted original price
  - `discount` (string, optional): Discount percentage or amount

### Optional Parameters/Variables
- `carousel_id` (string): Custom ID for the carousel (default: 'product-carousel')
- `carousel_title` (string): Title to display above the carousel

### Example Usage
```html
{% include "webshop/templates/includes/product_carousel.html" %}

<!-- With custom products -->
{% set website_items = [
  {
    "route": "products/laptop-pro-15",
    "web_item_name": "Laptop Pro 15\"",
    "website_image": "/files/laptop-pro-15.jpg",
    "abbr": "LP",
    "description": "High-performance laptop for professionals",
    "price": 1299.99,
    "formatted_price": "$1,299.99",
    "formatted_mrp": "$1,599.99",
    "discount": "19% off"
  },
  {
    "route": "products/wireless-mouse",
    "item_name": "Wireless Mouse",
    "website_image": "/files/wireless-mouse.jpg",
    "abbr": "WM",
    "description": "Ergonomic wireless mouse",
    "price": 29.99,
    "formatted_price": "$29.99"
  }
] %}

{% set carousel_title = "Featured Products" %}
{% set carousel_id = "featured-products" %}
{% include "webshop/templates/includes/product_carousel.html" with context %}
```

### Dependencies
- **CSS:** Embedded within the template with:
  - Responsive breakpoints
  - Hover effects and animations
  - Schema.org structured data markup
- **JavaScript:** Self-contained carousel logic with:
  - Touch/swipe event handling
  - Auto-play functionality (5-second intervals)
  - Image preloading for performance
  - Responsive item count adjustment

---

## Search Box

**File:** `/webshop/templates/includes/search_box.html`

### Purpose and Functionality
The search box provides a product search interface with:
- Real-time search with dropdown results
- Product thumbnails in search results
- Price display with discounts
- Brand information
- Recent search functionality
- No jQuery dependency

### Required Context Variables
None - the component is self-contained and loads its JavaScript dynamically.

### Optional Parameters/Variables
None - the component uses default configuration.

### Example Usage
```html
<!-- Basic inclusion -->
{% include "webshop/templates/includes/search_box.html" %}
```

### Dependencies
- **CSS:** Embedded within the template with custom styling for:
  - Search input with icon
  - Dropdown results container
  - Product result items with thumbnails
  - Price and discount display
- **JavaScript:** 
  - Dynamically loads `/assets/webshop/js/product_ui/search_no_jquery.js`
  - Initializes `webshop.ProductSearchNoJQuery` class

---

## User Header

**File:** `/webshop/templates/includes/user_header.html`

### Purpose and Functionality
The user header provides authentication and user account functionality:
- Login button for guests with login dialog
- User avatar and greeting for logged-in users
- Dropdown menu with account links:
  - My account
  - My orders
  - My addresses
  - My wishlist
  - Logout
- Responsive design for mobile integration

### Required Context Variables
- `frappe.session.user` (string): Current user (automatically available)
- `get_first_name()` function (server-side helper)

### Optional Parameters/Variables
None - the component is self-contained.

### Example Usage
```html
<!-- Basic inclusion -->
{% include "webshop/templates/includes/user_header.html" %}

<!-- The component automatically adapts based on login state -->
```

### Dependencies
- **CSS:** Embedded styles for:
  - Authentication wrapper and button
  - Avatar display using Frappe's avatar system
  - Dropdown menu styling
  - Login dialog customization
- **JavaScript:** 
  - Login dialog for guests (includes frappe-mock.js and auth_dialog.js)
  - Dropdown toggle for logged-in users
  - Logout functionality via AJAX
- **Macros:** Uses Frappe's `avatar` macro from `frappe/templates/includes/avatar_macro.html`

---

## Wishlist Component

**File:** `/webshop/templates/includes/wishlist_component.html`

### Purpose and Functionality
The wishlist component provides a wishlist icon with item count badge:
- Heart icon linking to wishlist page
- Dynamic badge showing number of wishlist items
- Only shown for logged-in users
- Automatically hidden on the wishlist page itself

### Required Context Variables
The component calls `get_wishlist_data()` internally which provides:
- `wishlist_items_count` (int): Number of items in the wishlist

### Optional Parameters/Variables
None - the component is self-contained.

### Example Usage
```html
<!-- Basic inclusion (only shows for logged-in users) -->
{% include "webshop/templates/includes/wishlist_component.html" %}

<!-- Component automatically hides on /wishlist page and for guests -->
```

### Dependencies
- **CSS:** Embedded styles for:
  - Wishlist button and icon
  - Badge positioning and styling
- **JavaScript:** Simple script to:
  - Read wishlist item count
  - Show/hide badge based on count
- **Server-side:** `get_wishlist_data()` function

---

## General Usage Notes

1. **Context Passing**: When including templates with custom variables, use `with context`:
   ```html
   {% set custom_var = "value" %}
   {% include "template_path.html" with context %}
   ```

2. **Translation Support**: All user-facing text uses Frappe's translation function `_()`:
   ```html
   {{ _("Text to translate") }}
   ```

3. **Responsive Design**: All components are mobile-first and responsive by default.

4. **Caching**: Some components use caching for performance (e.g., mobile menu navigation).

5. **Page Exclusions**: Cart and wishlist components automatically exclude themselves from their respective pages to avoid conflicts.

6. **Authentication State**: Components adapt automatically based on user login state via `frappe.session.user`.