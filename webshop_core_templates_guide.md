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
- `view_more_link` (string): URL for "View More" button (shows button if provided)
- `view_more_text` (string): Custom text for "View More" button (default: "View More")

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

<!-- With View More button -->
{% set carousel_title = "Popular Brands" %}
{% set carousel_id = "popular-brands" %}
{% set view_more_link = "/shop-by-category?tab=brand" %}
{% set view_more_text = "View All Brands" %}
{% include "webshop/templates/includes/brand_carousel.html" %}
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
- Automatic product fetching from database if no list provided
- Real-time price display with currency formatting
- Discount badges and strikethrough pricing
- Category display
- "Explore" button for product details
- Touch/swipe support
- Auto-play with pause on hover
- Responsive layout (1-4 products per view)
- Support for discount-only filtering

### Required Context Variables
None - the carousel will automatically fetch the latest published products if no list is provided.

### Optional Parameters/Variables
- `carousel_id` (string): Custom ID for the carousel (auto-generated if not provided)
- `carousel_title` (string): Title to display above the carousel
- `show_discounted_only` (bool): If True, only shows products with discounts (default: False)
- `carousel_limit` (int): Maximum number of products to display (default: 8)
- `website_items` (list): Custom list of products (overrides automatic fetching)
- `view_more_link` (string): URL for "View More" button (shows button if provided)
- `view_more_text` (string): Custom text for "View More" button (default: "View More")

### Example Usage
```html
<!-- Basic usage (fetches latest 8 products) -->
{% include "webshop/templates/includes/product_carousel.html" %}

<!-- Show only discounted products with View More button -->
{% set carousel_id = "promo-products" %}
{% set carousel_title = "Promotions" %}
{% set show_discounted_only = True %}
{% set carousel_limit = 12 %}
{% set view_more_link = "/all-products?discount=true" %}
{% set view_more_text = "View All Promotions" %}
{% include "webshop/templates/includes/product_carousel.html" %}

<!-- Multiple carousels on same page (IMPORTANT: reset variables) -->
{% set carousel_id = "new-products" %}
{% set carousel_title = "New Arrivals" %}
{% set show_discounted_only = False %}  <!-- Reset to False -->
{% set website_items = None %}  <!-- Reset to None -->
{% include "webshop/templates/includes/product_carousel.html" %}

{% set carousel_id = "sale-products" %}
{% set carousel_title = "On Sale" %}
{% set show_discounted_only = True %}
{% set website_items = None %}
{% include "webshop/templates/includes/product_carousel.html" %}

<!-- With custom product list -->
{% set carousel_id = "featured" %}
{% set carousel_title = "Featured Products" %}
{% set website_items = frappe.get_all("Website Item", 
    filters={"published": 1, "featured": 1}, 
    fields=["name", "web_item_name", "route", "website_image", "item_group"],
    limit=6
) %}
{% include "webshop/templates/includes/product_carousel.html" %}
```

### Important Notes for Multiple Carousels
When using multiple carousels on the same page, **always reset variables** between includes:
- Set `show_discounted_only = False` if not filtering by discount
- Set `website_items = None` to trigger automatic fetching
- Use unique `carousel_id` values to avoid conflicts

### Dependencies
- **CSS:** Embedded within the template with:
  - Responsive breakpoints
  - Discount badge styling
  - Hover effects and animations
- **JavaScript:** Self-contained carousel logic with:
  - Unique initialization per carousel
  - Touch/swipe event handling
  - Auto-play functionality (5-second intervals)
  - Responsive item count adjustment
- **Server-side:** 
  - Automatic price fetching from Item Price doctype
  - Discount calculation based on price lists
  - Currency formatting from Webshop Settings

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