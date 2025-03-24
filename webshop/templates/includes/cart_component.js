const cartDataElement = document.getElementById('cart-data');
const cartBadge = document.getElementById('cartBadge');
const cartButton = document.getElementById('cartButton');
const cartOverlay = document.getElementById('cartOverlay');
const sideCart = document.getElementById('sideCart');
const closeCartButton = document.getElementById('closeCartButton');
const cartItemsContainer = document.getElementById('cartItemsContainer');
const emptyCart = document.getElementById('emptyCart');
const cartFooter = document.getElementById('cartFooter');
const cartTotal = document.getElementById('cartTotal');
const cartSubtotal = document.getElementById('cartSubtotal');
const cartTaxDetails = document.getElementById('cartTaxDetails');
const cartTaxesContainer = document.getElementById('cartTaxesContainer');
const cartLoading = document.getElementById('cartLoading');

// Initialize page data
let pageData = { 
  cart_items: [], 
  cart_total: 0, 
  cart_items_count: 0,
  currency: '',
  cart_info: {},
  tax_info: []
};

if (cartDataElement) {
  try {
    // Get cart data from dataset
    pageData = {
      cart_items: JSON.parse(cartDataElement.dataset.cartItems || '[]'),
      cart_total: parseFloat(cartDataElement.dataset.cartTotal || '0'),
      cart_items_count: parseInt(cartDataElement.dataset.cartItemsCount || '0'),
      currency: cartDataElement.dataset.currency || ''
    };
    
    // Get detailed cart information if available
    if (cartDataElement.dataset.cartInfo) {
      pageData.cart_info = JSON.parse(cartDataElement.dataset.cartInfo || '{}');
    }
    
    if (cartDataElement.dataset.taxInfo) {
      pageData.tax_info = JSON.parse(cartDataElement.dataset.taxInfo || '[]');
    }
  } catch (e) {
    console.error('Error parsing cart data:', e);
  }
}

// Open cart with animation
function openCart() {
  if (cartOverlay) {
    // Make overlay visible before animation
    cartOverlay.style.visibility = 'visible';
    cartOverlay.style.display = 'inherit';
    
    // Trigger reflow for animation to work
    void cartOverlay.offsetWidth;
    
    // Add active class to trigger animation
    cartOverlay.classList.add('active');
    
    if (sideCart) {
      sideCart.classList.add('active');
    }
  }
}

// Close cart with animation
function closeCart() {
  if (cartOverlay && cartOverlay.classList.contains('active')) {
    // Remove active class to trigger closing animation
    cartOverlay.classList.remove('active');
    
    if (sideCart) {
      sideCart.classList.remove('active');
    }
    
    // Wait for animation to finish before hiding overlay
    setTimeout(() => {
      cartOverlay.style.visibility = 'hidden';
    }, 300);
  }
}

// Update cart interface
function updateCartUI() {
  // Update badge
  if (cartBadge) {
    if (pageData.cart_items_count > 0) {
      cartBadge.textContent = pageData.cart_items_count;
      cartBadge.style.display = 'flex';
    } else {
      cartBadge.style.display = 'none';
    }
  }

  // Update total amount with currency
  if (cartTotal) {
    cartTotal.textContent = formatPrice(pageData.cart_total);
  }
  
  // Update subtotal
  if (cartSubtotal) {
    const subtotal = pageData.cart_info.total || pageData.cart_info.net_total || pageData.cart_total || 0;
    cartSubtotal.textContent = formatPrice(subtotal);
  }

  // Show or hide interface based on content
  if (pageData.cart_items.length === 0) {
    if (emptyCart) emptyCart.style.display = 'block';
    if (cartItemsContainer) cartItemsContainer.style.display = 'none';
    if (cartFooter) cartFooter.style.display = 'none';
    if (cartTaxDetails) cartTaxDetails.style.display = 'none';
  } else {
    if (emptyCart) emptyCart.style.display = 'none';
    if (cartItemsContainer) {
      cartItemsContainer.style.display = 'block';
      renderCartItems();
    }
    if (cartFooter) cartFooter.style.display = 'block';
    
    // Show tax details if available
    if (pageData.tax_info && pageData.tax_info.length > 0) {
      renderTaxInfo();
      if (cartTaxDetails) cartTaxDetails.style.display = 'block';
    } else if (cartTaxDetails) {
      cartTaxDetails.style.display = 'none';
    }
  }
}

// Generate HTML for cart items
function renderCartItems() {
  if (!cartItemsContainer) return;

  cartItemsContainer.innerHTML = '';

  pageData.cart_items.forEach(item => {
    const itemElement = document.createElement('div');
    itemElement.className = 'cart-item';
    
    // Use thumbnail if available, otherwise use main image
    const imageUrl = item.thumbnail || item.website_image;
    // Create an abbreviation from the item name if none is provided
    const abbr = item.abbr || (item.item_name ? item.item_name.split(' ').map(w => w[0]).join('').toUpperCase() : '');
    const itemName = item.item_name || '';
    const quantity = item.qty || 1;
    const price = item.rate || 0;
    const brand = item.brand || '';
    const itemCode = item.item_code || '';
    const isGiftCard = item.is_gift_card || false;
    
    // Quantity controls HTML - disabled for gift cards
    const quantityControls = isGiftCard ? 
      `<div class="cart-item-quantity">
        <span class="qty-value">${quantity}</span>
      </div>` : 
      `<div class="cart-item-quantity">
        <button class="qty-btn minus" data-item-code="${itemCode}" data-action="decrease">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="currentColor" d="M5 11h14v2H5z"/></svg>
        </button>
        <span class="qty-value">${quantity}</span>
        <button class="qty-btn plus" data-item-code="${itemCode}" data-action="increase">
          <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="currentColor" d="M19 11h-6V5h-2v6H5v2h6v6h2v-6h6z"/></svg>
        </button>
      </div>`;
    
    itemElement.innerHTML = `
      <div class="cart-item-image">
        ${(item.thumbnail || item.website_image) ? 
          `<img src="${imageUrl}" alt="${itemName}" onerror="this.onerror=null; this.parentNode.innerHTML='<div class=\\'item-abbr\\'>${abbr}</div>';" />` : 
          `<div class="item-abbr">${abbr}</div>`}
      </div>
      <div class="cart-item-details">
        ${brand ? `<div class="cart-item-brand">${brand}</div>` : ''}
        <div class="cart-item-name">
          ${item.route ? 
            `<a href="/${item.route}" class="item-link">${itemName}</a>` : 
            itemName}
        </div>
        <div class="cart-item-price">${formatPrice(price)}</div>
        ${quantityControls}
      </div>
      <button class="remove-item" data-item-code="${itemCode}">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12L19 6.41z"/></svg>
      </button>
    `;
    
    cartItemsContainer.appendChild(itemElement);
  });

  // Add event listeners for buttons
  addCartButtonEvents();
}

// Handle quantity change
function handleQuantityChange(e) {
  // Find the button, even if the user clicks on a child element (like the SVG)
  const button = e.target.closest('.qty-btn, .cart-btn');
  if (!button) {
    return;
  }
  
  const itemCode = button.dataset.itemCode || button.closest('[data-item-code]')?.dataset.itemCode;
  const action = button.dataset.action || (button.dataset.dir === 'up' ? 'increase' : 'decrease');

  if (!itemCode) {
    return;
  }

  // Find the quantity element
  const qtyElement = button.parentElement.querySelector('.qty-value') || 
                     button.closest('.number-spinner')?.querySelector('input.cart-qty');
  
  if (!qtyElement) {
    return;
  }
  
  let currentQty = parseInt(qtyElement.textContent || qtyElement.value) || 1;
  let newQty = action === 'increase' ? currentQty + 1 : Math.max(1, currentQty - 1);

  // If quantity doesn't change, do nothing
  if (newQty === currentQty) return;
  
  // Disable button during update
  button.disabled = true;
  
  // Update quantity display immediately for instant visual feedback
  if (qtyElement.tagName === 'INPUT') {
    qtyElement.value = newQty;
  } else {
    qtyElement.textContent = newQty;
  }
  
  // Add class to indicate update state
  const cartItem = button.closest('.cart-item, tr[data-name]');
  if (cartItem) {
    // Remove old animation class if present
    cartItem.classList.remove('updating');
    
    // Add new ripple effect class
    cartItem.classList.add('updating-ripple');
    
    // Add loading overlay with dots
    const existingOverlay = cartItem.querySelector('.item-loading-overlay');
    if (!existingOverlay) {
      const loadingOverlay = document.createElement('div');
      loadingOverlay.className = 'item-loading-overlay';
      loadingOverlay.innerHTML = `
        <div class="loading-dots">
          <span></span>
          <span></span>
          <span></span>
        </div>
      `;
      cartItem.style.position = 'relative'; // Ensure parent element is positioned
      cartItem.appendChild(loadingOverlay);
    }
  }
  
  // Check if a coupon or loyalty points are applied before updating quantity
  frappe.call({
    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
    callback: (r) => {
      if (r.message && r.message.doc) {
        const doc = r.message.doc;
        // Check if a coupon or loyalty points are applied
        if (doc.coupon_code || doc.gift_card_coupon) {
          // Remove the coupon before updating the quantity
          frappe.call({
            method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
            callback: (r) => {
              if (r.message) {
                frappe.show_alert({
                  message: __('Le coupon a été supprimé pour mettre à jour la quantité'),
                  indicator: 'blue'
                });
                // Continue with the quantity update
                updateCartItemQuantity(itemCode, newQty, cartItem, currentQty, qtyElement, button);
              }
            }
          });
        } else if (doc.loyalty_points) {
          // Remove loyalty points before updating the quantity
          frappe.call({
            method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
            callback: (r) => {
              if (r.message) {
                frappe.show_alert({
                  message: __('Les points de fidélité ont été supprimés pour mettre à jour la quantité'),
                  indicator: 'blue'
                });
                // Continue with the quantity update
                updateCartItemQuantity(itemCode, newQty, cartItem, currentQty, qtyElement, button);
              }
            }
          });
        } else {
          // No coupon or loyalty points, update quantity directly
          updateCartItemQuantity(itemCode, newQty, cartItem, currentQty, qtyElement, button);
        }
      } else {
        // No cart data, update quantity directly
        updateCartItemQuantity(itemCode, newQty, cartItem, currentQty, qtyElement, button);
      }
    }
  });
}

// Helper function to update cart item quantity
function updateCartItemQuantity(itemCode, newQty, cartItem, currentQty, qtyElement, button) {
  // Call API to update quantity
  frappe.call({
    method: 'webshop.webshop.utils.cart_helpers.update_cart',
    args: {
      item_code: itemCode,
      qty: newQty,
      additional_notes: '',
      with_items: 1
    },
    freeze: false, // Do not block the user interface
    callback: function(r) {
      if (r.message && r.message.success !== false) {
        try {
          // Update item price and total
          updateItemPrice(cartItem, r.message, itemCode, newQty, currentQty);
          
          // Update cart totals without refreshing the entire cart
          updateCartTotals(r.message);
          
          // Display animated badge to indicate successful update
          updateCartBadge(true);
        } catch (err) {
          console.error("Error updating interface:", err);
          // In case of error during processing, refresh the entire cart
          refreshCart();
        }
      } else {
        // Restore original value on failure
        if (qtyElement.tagName === 'INPUT') {
          qtyElement.value = currentQty;
        } else {
          qtyElement.textContent = currentQty;
        }
        // Refresh the cart to ensure everything is correct
        refreshCart();
      }
      
      // Remove update state class and overlay
      if (cartItem) {
        cartItem.classList.remove('updating-ripple');
        
        // Remove loading overlay
        const loadingOverlay = cartItem.querySelector('.item-loading-overlay');
        if (loadingOverlay) {
          loadingOverlay.remove();
        }
        
        // Add flash effect to indicate success
        cartItem.style.transition = 'background-color 0.5s ease';
        cartItem.style.backgroundColor = 'rgba(40, 167, 69, 0.1)';
        setTimeout(() => {
          cartItem.style.backgroundColor = '';
        }, 800);
      }
      
      // Reactivate button
      button.disabled = false;
    },
    error: function(err) {
      console.error('Error updating cart:', err);
      // Restore original value on error
      if (qtyElement.tagName === 'INPUT') {
        qtyElement.value = currentQty;
      } else {
        qtyElement.textContent = currentQty;
      }
      
      // Remove ripple effect and loading overlay
      if (cartItem) {
        cartItem.classList.remove('updating-ripple');
        
        // Remove loading overlay
        const loadingOverlay = cartItem.querySelector('.item-loading-overlay');
        if (loadingOverlay) {
          loadingOverlay.remove();
        }
        
        // Add flash effect to indicate error
        cartItem.style.transition = 'background-color 0.5s ease';
        cartItem.style.backgroundColor = 'rgba(220, 53, 69, 0.1)';
        setTimeout(() => {
          cartItem.style.backgroundColor = '';
        }, 800);
      }
      
      // Reactivate button
      button.disabled = false;
      
      // Refresh the cart to retrieve the correct state
      refreshCart();
    }
  });
}

// Handle item removal
function handleRemoveItem(e) {
  // Find the button, even if the user clicks on a child element (like the SVG)
  const button = e.target.closest('.remove-item, .remove-cart-item');
  if (!button) {
    console.error("Button not found");
    return;
  }
  
  const itemCode = button.dataset.itemCode || button.closest('[data-item-code]')?.dataset.itemCode;

  if (!itemCode) {
    console.error("Item code not found");
    return;
  }

  // Disable button during removal
  button.disabled = true;
  
  // Add immediate visual effect
  const cartItem = button.closest('.cart-item, tr[data-name]');
  if (cartItem) {
    // Remove other animation classes
    cartItem.classList.remove('removing', 'updating', 'updating-ripple');
    
    // Add slide animation class
    cartItem.classList.add('removing-slide');
    
    // Save current height for later animation
    cartItem.style.height = cartItem.offsetHeight + 'px';
    cartItem.style.overflow = 'hidden';
  }

  // Check if a coupon or loyalty points are applied before removing item
  frappe.call({
    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
    callback: (r) => {
      if (r.message && r.message.doc) {
        const doc = r.message.doc;
        // Check if a coupon or loyalty points are applied
        if (doc.coupon_code || doc.gift_card_coupon) {
          // Remove the coupon before removing the item
          frappe.call({
            method: 'webshop.webshop.shopping_cart.cart.remove_coupon_code',
            callback: (r) => {
              if (r.message) {
                frappe.show_alert({
                  message: __('Le coupon a été supprimé pour retirer le produit'),
                  indicator: 'blue'
                });
                // Continue with the item removal
                removeCartItem(itemCode, cartItem, button);
              }
            }
          });
        } else if (doc.loyalty_points) {
          // Remove loyalty points before removing the item
          frappe.call({
            method: 'webshop.webshop.shopping_cart.cart.remove_loyalty_points',
            callback: (r) => {
              if (r.message) {
                frappe.show_alert({
                  message: __('Les points de fidélité ont été supprimés pour retirer le produit'),
                  indicator: 'blue'
                });
                // Continue with the item removal
                removeCartItem(itemCode, cartItem, button);
              }
            }
          });
        } else {
          // No coupon or loyalty points, remove item directly
          removeCartItem(itemCode, cartItem, button);
        }
      } else {
        // No cart data, remove item directly
        removeCartItem(itemCode, cartItem, button);
      }
    }
  });
}

// Helper function to remove cart item
function removeCartItem(itemCode, cartItem, button) {
  // Call API to remove the item (qty=0 means remove)
  frappe.call({
    method: 'webshop.webshop.utils.cart_helpers.update_cart',
    args: {
      item_code: itemCode,
      qty: 0,
      additional_notes: '',
      with_items: 1
    },
    callback: function(r) {
      if (r.message && r.message.success !== false) {        
        // Close animation once slide animation is complete
        if (cartItem) {
          // Wait for the slide animation to finish
          setTimeout(() => {
            // Height reduction animation
            cartItem.style.transition = 'height 0.3s ease';
            cartItem.style.height = '0';
            cartItem.style.padding = '0';
            cartItem.style.margin = '0';
            
            // Remove element after animation
            setTimeout(() => {
              if (cartItem.parentNode) {
                cartItem.parentNode.removeChild(cartItem);
              }
              
              // Update totals
              updateCartTotals(r.message);
              
              // If this was the last item, update the interface
              if (r.message.items && r.message.items.length === 0) {
                updateCartUI();
              }
            }, 300);
          }, 500);
        } else {
          // If we cannot animate, simply update
          updateCartTotals(r.message);
          updateCartUI();
        }
      } else {
        // Restore appearance on failure
        if (cartItem) {
          cartItem.classList.remove('removing-slide');
          cartItem.style.height = '';
          cartItem.style.overflow = '';
          
          // Add flash effect to indicate error
          cartItem.style.transition = 'background-color 0.5s ease';
          cartItem.style.backgroundColor = 'rgba(220, 53, 69, 0.1)';
          setTimeout(() => {
            cartItem.style.backgroundColor = '';
          }, 800);
        }
        
        button.disabled = false;
        // Refresh to ensure state is correct
        refreshCart();
      }
    },
    error: function(err) {
      console.error('Error removing item:', err);
      
      // Restore appearance on failure
      if (cartItem) {
        cartItem.classList.remove('removing-slide');
        cartItem.style.height = '';
        cartItem.style.overflow = '';
        
        // Add flash effect to indicate error
        cartItem.style.transition = 'background-color 0.5s ease';
        cartItem.style.backgroundColor = 'rgba(220, 53, 69, 0.1)';
        setTimeout(() => {
          cartItem.style.backgroundColor = '';
        }, 800);
      }
      
      button.disabled = false;
      
      // Refresh to ensure state is correct
      refreshCart();
    }
  });
}

function refreshCart(forceRender = false) {
  // Display loading indicator
  if (cartLoading) cartLoading.style.display = 'block';
  
  // Variable to track if a refresh is already in progress
  if (window.isRefreshing && !forceRender) {
    return;
  }
  
  window.isRefreshing = true;
  
  // Use Frappe API to fetch current cart data
  frappe.call({
    method: 'webshop.webshop.shopping_cart.cart.get_cart_quotation',
    args: {
      with_items: 1
    },
    freeze: false,
    callback: function(r) {
      if (r.message && r.message.doc) {        
        try {
          // Extract relevant data
          const quotation = r.message.doc;
          
          // Update base data
          pageData.cart_items = quotation.items || [];
          pageData.cart_total = quotation.grand_total || 0;
          pageData.cart_items_count = quotation.total_qty || 0;
          pageData.cart_info = r.message;
          
          // Extract tax information
          pageData.tax_info = [];
          if (quotation.taxes && quotation.taxes.length > 0) {
            quotation.taxes.forEach(tax => {
              let taxDescription = tax.description;
              if (taxDescription.includes('%')) {
                taxDescription = taxDescription.split('%')[0] + '%';
              }
              pageData.tax_info.push({
                description: taxDescription,
                tax_amount: tax.tax_amount,
                rate: tax.rate
              });
            });
          }
          
          // Update the interface
          updateCartUI();
        } catch (err) {
          console.error("Error processing data:", err);
        }
      } else {
        // If no data, consider the cart is empty
        pageData.cart_items = [];
        pageData.cart_total = 0;
        pageData.cart_items_count = 0;
        pageData.tax_info = [];
        updateCartUI();
      }
      
      // Hide loading indicator
      if (cartLoading) cartLoading.style.display = 'none';
      
      // Reset refresh indicator
      window.isRefreshing = false;
    },
    error: function(err) {
      console.error('Error refreshing cart:', err);
      if (cartLoading) cartLoading.style.display = 'none';
      window.isRefreshing = false;
    }
  });
}

// Function to update the price of a specific item
function updateItemPrice(cartItem, cartData, itemCode, newQty, oldQty) {
  if (!cartItem) return;
  
  let itemRate = 0;
  
  // Search for rate/price unit in different data structures
  if (Array.isArray(cartData.items)) {
    // Array format
    const updatedItem = cartData.items.find(item => 
      item.item_code === itemCode || 
      (item.item_code && item.item_code.includes(itemCode))
    );
    if (updatedItem) {
      itemRate = updatedItem.rate || updatedItem.price_rate || 0;
    }
  } else if (typeof cartData.items === 'object' && cartData.items !== null) {
    // Format objet
    for (const key in cartData.items) {
      const item = cartData.items[key];
      if (item && (item.item_code === itemCode || 
                  (item.item_code && item.item_code.includes(itemCode)))) {
        itemRate = item.rate || item.price_rate || 0;
        break;
      }
    }
  } else if (typeof cartData.items === 'string') {
    // HTML format
    try {
      const tempDiv = document.createElement('div');
      tempDiv.innerHTML = cartData.items;
      
      // Search by item code
      const itemElement = tempDiv.querySelector(`[data-item-code="${itemCode}"]`) || 
                          tempDiv.querySelector(`[data-item-code*="${itemCode}"]`) ||
                          tempDiv.querySelector(`tr[data-name*="${itemCode}"]`);
      
      if (itemElement) {
        // Search for unit price in different formats
        const rateElement = itemElement.querySelector('.item-rate, .rate');
        if (rateElement) {
          const rateText = rateElement.textContent.trim();
          const rateMatch = rateText.match(/([0-9.,]+)/g);
          if (rateMatch && rateMatch.length > 0) {
            itemRate = parseFloat(rateMatch[0].replace(/,/g, '.'));
          }
        }
        
        // If no rate found, search for total price and divide by quantity
        if (itemRate === 0) {
          const priceElement = itemElement.querySelector('.original-price, .amount, .item-amount');
          if (priceElement) {
            const priceText = priceElement.textContent.trim();
            const priceMatch = priceText.match(/([0-9.,]+)/g);
            if (priceMatch && priceMatch.length > 0) {
              const totalAmount = parseFloat(priceMatch[0].replace(/,/g, '.'));
              // Si on trouve une quantité dans la DOM, utiliser cette valeur, sinon utiliser newQty
              const qtyElement = itemElement.querySelector('.cart-qty, .qty-value');
              const itemQty = qtyElement ? 
                              parseInt(qtyElement.value || qtyElement.textContent) || newQty : 
                              newQty;
              itemRate = totalAmount / itemQty;
            }
          }
        }
      }
    } catch (e) {
      console.error("Error parsing HTML:", e);
    }
  }
  
  // If no rate found, try other ways
  if (itemRate === 0 && cartData.doc && cartData.doc.items) {
    // Try to find the element in doc.items
    const docItem = cartData.doc.items.find(item => 
      item.item_code === itemCode || 
      (item.item_code && item.item_code.includes(itemCode))
    );
    if (docItem) {
      itemRate = docItem.rate || docItem.price_rate || 0;
    }
  }

  // Update the displayed price for this item
  if (itemRate > 0) {
    // Update the unit price
    const rateElements = cartItem.querySelectorAll('.item-rate, .rate');
    rateElements.forEach(el => {
      el.textContent = `Prix: ${itemRate.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',')} / Unité`;
    });
    
    // Update the total price
    const priceElements = cartItem.querySelectorAll('.original-price, .amount, .item-amount');
    const totalPrice = itemRate * newQty;
    priceElements.forEach(el => {
      el.textContent = totalPrice.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
    });
  } else {
    // Fallback method: use current price to estimate
    const priceElement = cartItem.querySelector('.original-price, .amount, .item-amount');
    if (priceElement) {
      const currentPrice = priceElement.textContent;
      const priceMatch = currentPrice.match(/([0-9.,]+)/g);
      if (priceMatch && priceMatch.length > 0) {
        const currentTotal = parseFloat(priceMatch[0].replace(/,/g, '.'));
        const estimatedRate = currentTotal / oldQty;
        const newTotal = estimatedRate * newQty;
        priceElement.textContent = newTotal.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, ',');
      }
    }
  }
}

// Update cart totals without refreshing items
function updateCartTotals(cartData) {
  if (!cartData) return;

  // Update base data
  pageData.cart_info = cartData;
  
  // Extract totals based on the received data structure
  let extractedTotal = 0;
  let extractedItemCount = 0;
  let extractedSubtotal = 0;
  
  // --- EXTRACTION DU TOTAL ---
  
  // Method 1: Direct properties in the object
  if (typeof cartData.grand_total === 'number') {
    extractedTotal = cartData.grand_total;
  } else if (typeof cartData.total === 'number') {
    extractedTotal = cartData.total;
  } else if (cartData.doc && typeof cartData.doc.grand_total === 'number') {
    extractedTotal = cartData.doc.grand_total;
  } else if (cartData.doc && typeof cartData.doc.total === 'number') {
    extractedTotal = cartData.doc.total;
  }
  
  // Method 2: Extract from HTML if total is a string
  if ((extractedTotal === 0 || isNaN(extractedTotal)) && 
      (typeof cartData.grand_total === 'string' || typeof cartData.total === 'string')) {
    const totalString = cartData.grand_total || cartData.total || '';
    // Search for patterns like "₹1,234.56" or "€123.45" or "$123.45" or "123.45 CHF"
    const priceMatch = totalString.match(/([₹€$£¥])?[\s]?([0-9.,]+)(?:\s*([A-Z]{3}))?/);
    if (priceMatch && priceMatch[2]) {
      // Convert to number by replacing commas with dots for the decimal
      extractedTotal = parseFloat(priceMatch[2].replace(/,/g, '.'));
    }
  }
  
  // Method 3: Extract from HTML if totals are in taxes_and_totals
  if ((extractedTotal === 0 || isNaN(extractedTotal)) && typeof cartData.taxes_and_totals === 'string') {
    const totalMatch = cartData.taxes_and_totals.match(/total[^>]*>([^<]*)/i);
    if (totalMatch && totalMatch[1]) {
      const priceMatch = totalMatch[1].match(/([0-9.,]+)/);
      if (priceMatch && priceMatch[1]) {
        extractedTotal = parseFloat(priceMatch[1].replace(/,/g, '.'));
      }
    }
    
    // Research specifically in the "Total TTC" row
    if ((extractedTotal === 0 || isNaN(extractedTotal))) {
      const ttcMatch = cartData.taxes_and_totals.match(/Total TTC[^<]*<\/td>\s*<td[^>]*>([^<]*)/);
      if (ttcMatch && ttcMatch[1]) {
        const priceMatch = ttcMatch[1].match(/([0-9.,]+)/);
        if (priceMatch && priceMatch[1]) {
          extractedTotal = parseFloat(priceMatch[1].replace(/,/g, '.'));
        }
      }
    }
  }
  
  // Method 4: Search in the HTML of the "total" field
  if ((extractedTotal === 0 || isNaN(extractedTotal)) && typeof cartData.total === 'string') {
    const totalMatch = cartData.total.match(/totals[^>]*>([^<]*)</);
    if (totalMatch && totalMatch[1]) {
      const priceMatch = totalMatch[1].match(/([0-9.,]+)/);
      if (priceMatch && priceMatch[1]) {
        extractedTotal = parseFloat(priceMatch[1].replace(/,/g, '.'));
      }
    }
  }
  
  // --- SUBTOTAL EXTRACTION ---
  
  // Method 1: Direct properties
  if (typeof cartData.net_total === 'number') {
    extractedSubtotal = cartData.net_total;
  } else if (typeof cartData.base_total === 'number') {
    extractedSubtotal = cartData.base_total;
  } else if (typeof cartData.subtotal === 'number') {
    extractedSubtotal = cartData.subtotal;
  } else if (cartData.doc && typeof cartData.doc.net_total === 'number') {
    extractedSubtotal = cartData.doc.net_total;
  }
  
  // Method 2: Extract from HTML in taxes_and_totals
  if ((extractedSubtotal === 0 || isNaN(extractedSubtotal)) && typeof cartData.taxes_and_totals === 'string') {
    // Search for "Net Total" or "Sous-total"
    const subtotalMatch = cartData.taxes_and_totals.match(/Net Total|Sous-total[^<]*<\/td>\s*<td[^>]*>([^<]*)/i);
    if (subtotalMatch && subtotalMatch[1]) {
      const priceMatch = subtotalMatch[1].match(/([0-9.,]+)/);
      if (priceMatch && priceMatch[1]) {
        extractedSubtotal = parseFloat(priceMatch[1].replace(/,/g, '.'));
      }
    }
  }
  
  // --- ITEM COUNT EXTRACTION ---
  
  // Method 1: Direct property
  if (typeof cartData.total_qty === 'number') {
    extractedItemCount = cartData.total_qty;
  } else if (cartData.doc && typeof cartData.doc.total_qty === 'number') {
    extractedItemCount = cartData.doc.total_qty;
  } else if (typeof cartData.total_qty === 'string') {
    const qtyMatch = cartData.total_qty.match(/(\d+)/);
    if (qtyMatch && qtyMatch[1]) {
      extractedItemCount = parseInt(qtyMatch[1]);
    }
  }
  
  // Method 2: Count items manually
  if ((extractedItemCount === 0 || isNaN(extractedItemCount)) && Array.isArray(cartData.items)) {
    // Sum quantities or count items
    extractedItemCount = cartData.items.reduce((total, item) => total + (parseInt(item.qty) || 1), 0);
  } 
  // Method 3: Extract number of items from text
  else if ((extractedItemCount === 0 || isNaN(extractedItemCount)) && 
          typeof cartData.taxes_and_totals === 'string') {
    const itemsMatch = cartData.taxes_and_totals.match(/\((\d+)[^\)]*Items\)/i);
    if (itemsMatch && itemsMatch[1]) {
      extractedItemCount = parseInt(itemsMatch[1]);
    }
  }
  
  // If we still don't have an item count, estimate from the HTML response
  if ((extractedItemCount === 0 || isNaN(extractedItemCount)) && typeof cartData.items === 'string') {
    const qtyInputs = cartData.items.match(/cart-qty[^>]*value="(\d+)"/g) || [];
    if (qtyInputs.length > 0) {
      extractedItemCount = qtyInputs.reduce((total, input) => {
        const match = input.match(/value="(\d+)"/);
        return total + (match ? parseInt(match[1]) : 0);
      }, 0);
    } else {
      // Count the number of elements cart-item or data-item-code
      const itemMatches = (cartData.items.match(/data-item-code=|data-name=/g) || []).length;
      extractedItemCount = itemMatches > 0 ? itemMatches : 0;
    }
  }
  
  // --- TAX EXTRACTION ---
  
  let extractedTaxes = [];
  
  // Method 1: Direct tax array
  if (Array.isArray(cartData.taxes)) {
    extractedTaxes = cartData.taxes.map(tax => {
      if (tax.description.includes('%')) {
        tax.description = tax.description.split('%')[0] + '%';
      }
      return {
        description: tax.description || tax.account_head || tax.title || 'Taxe',
        amount: tax.tax_amount || tax.amount || 0
      };
    });
  } 
  // Method 2: Taxes in the document
  else if (cartData.doc && Array.isArray(cartData.doc.taxes)) {
    extractedTaxes = cartData.doc.taxes.map(tax => {
      if (tax.description.includes('%')) {
        tax.description = tax.description.split('%')[0] + '%';
      }
      return {
        description: tax.description || tax.account_head || tax.title || 'Taxe',
        amount: tax.tax_amount || tax.amount || 0
      };
    });
  }
  // Method 3: Extract from HTML
  else if (typeof cartData.taxes_and_totals === 'string') {
    const taxPattern = /<tr>\s*<td[^>]*>(TVA[^<]*|Tax[^<]*)<\/td>\s*<td[^>]*>([^<]*)<\/td>\s*<\/tr>/gi;
    let match;
    while ((match = taxPattern.exec(cartData.taxes_and_totals)) !== null) {
      const taxName = match[1].trim();
      const taxValue = match[2].trim();
      const valueMatch = taxValue.match(/([0-9.,]+)/);
      if (valueMatch && valueMatch[1]) {
        extractedTaxes.push({
          description: taxName,
          amount: parseFloat(valueMatch[1].replace(/,/g, '.'))
        });
      }
    }
    
    // Also search for shipping costs
    const shippingPattern = /<tr>\s*<td[^>]*>(Post Express|Shipping[^<]*)<\/td>\s*<td[^>]*>([^<]*)<\/td>\s*<\/tr>/i;
    const shippingMatch = cartData.taxes_and_totals.match(shippingPattern);
    if (shippingMatch) {
      const shippingName = shippingMatch[1].trim();
      const shippingValue = shippingMatch[2].trim();
      const valueMatch = shippingValue.match(/([0-9.,]+)/);
      if (valueMatch && valueMatch[1]) {
        extractedTaxes.push({
          description: shippingName,
          amount: parseFloat(valueMatch[1].replace(/,/g, '.'))
        });
      }
    }
  }
  
  // If we haven't found a subtotal but have a total and taxes
  if ((extractedSubtotal === 0 || isNaN(extractedSubtotal)) && 
      extractedTotal > 0 && extractedTaxes.length > 0) {
    const taxTotal = extractedTaxes.reduce((sum, tax) => sum + (tax.amount || 0), 0);
    extractedSubtotal = extractedTotal - taxTotal;
  }
  
  // If we still don't have a subtotal, use the total as an estimate
  if ((extractedSubtotal === 0 || isNaN(extractedSubtotal)) && extractedTotal > 0) {
    extractedSubtotal = extractedTotal;
  }
  
  // Update cart data with extracted values
  pageData.cart_total = !isNaN(extractedTotal) ? extractedTotal : 0;
  pageData.cart_items_count = !isNaN(extractedItemCount) ? extractedItemCount : 0;
  pageData.tax_info = extractedTaxes;
  
  // Update total display
  if (cartTotal) {
    cartTotal.textContent = formatPrice(pageData.cart_total);
  }
  
  // Update subtotal
  if (cartSubtotal && !isNaN(extractedSubtotal)) {
    cartSubtotal.textContent = formatPrice(extractedSubtotal);
    
    // Ensure the subtotal is visible
    const subtotalContainer = cartSubtotal.closest('.cart-subtotal') || cartSubtotal.closest('tr');
    if (subtotalContainer) {
      subtotalContainer.style.display = 'flex';
    }
  }
  
  // Update tax info
  if (extractedTaxes.length > 0) {
    renderTaxInfo();
    if (cartTaxDetails) cartTaxDetails.style.display = 'block';
  } else {
    if (cartTaxDetails) cartTaxDetails.style.display = 'none';
  }
  
  // Update cart badge in header
  updateCartBadge();
  
  // Show or hide cart footer based on items or total
  if (cartFooter) {
    const hasItems = pageData.cart_items_count > 0 || pageData.cart_total > 0;
    cartFooter.style.display = hasItems ? 'block' : 'none';
  }
  
  // Update empty cart state
  if (emptyCart && cartItemsContainer) {
    if (pageData.cart_items_count > 0 || pageData.cart_total > 0) {
      emptyCart.style.display = 'none';
      cartItemsContainer.style.display = 'block';
    } else {
      emptyCart.style.display = 'block';
      cartItemsContainer.style.display = 'none';
    }
  }
}

// Function to format price with currency
function formatPrice(price) {
  // Ensure price is a number
  const numPrice = parseFloat(price);
  
  // Check if it's a valid number
  if (isNaN(numPrice)) {
    return '0.00'; // Default value in case of error
    }
  
  // Format with correct separators for the country (comma for thousands, dot for decimals)
  return numPrice.toFixed(2).replace(/\B(?=(\d{3})+(?!\d))/g, "'") + ' CHF';
}

// Function to update cart badge with optional animation
function updateCartBadge(animate = false) {
  if (!cartBadge) return;
  
  if (pageData.cart_items_count > 0) {
    cartBadge.textContent = pageData.cart_items_count;
    cartBadge.style.display = 'flex';
    
    // Add animation to badge if requested
    if (animate) {
      cartBadge.classList.add('updated');
      setTimeout(() => cartBadge.classList.remove('updated'), 500);
    }
  } else {
    cartBadge.style.display = 'none';
  }
}

// Function to render tax information
function renderTaxInfo() {
  if (!cartTaxesContainer) return;
  
  cartTaxesContainer.innerHTML = '';
  
  // Check if we have tax information
  if (!pageData.tax_info || pageData.tax_info.length === 0) {
    cartTaxesContainer.style.display = 'none';
    if (cartTaxDetails) cartTaxDetails.style.display = 'none';
    return;
  }
  
  let hasTaxes = false;
  let totalTaxAmount = 0;
  
  // Loop through taxes and display them
  pageData.tax_info.forEach(tax => {
    // Determine tax name and amount
    let taxName = '';
    let taxAmount = 0;
    
    if (typeof tax === 'object') {
      // Standard object structure
      if (tax.description.includes('%')) {
        taxName = tax.description.split('%')[0] + '%';
      } else {
        taxName = tax.description || tax.account_head || tax.title || 'Taxe';
      }
      taxAmount = tax.tax_amount || tax.amount || 0;
      
      // Check if the amount is a string (can happen with certain responses)
      if (typeof taxAmount === 'string') {
        const match = taxAmount.match(/([0-9,]+\.?[0-9]*)/);
        if (match && match[1]) {
          taxAmount = parseFloat(match[1].replace(/,/g, ''));
        } else {
          taxAmount = 0;
        }
      }
    } else if (typeof tax === 'string') {
      // If it's a string, try to extract the name and amount
      const parts = tax.split(':');
      if (parts.length > 1) {
        taxName = parts[0].trim();
        const match = parts[1].match(/([0-9,]+\.?[0-9]*)/);
        if (match && match[1]) {
          taxAmount = parseFloat(match[1].replace(/,/g, ''));
        } else {
          taxAmount = 0;
        }
      } else {
        taxName = tax;
        taxAmount = 0;
      }
    }
    
    totalTaxAmount += taxAmount;
    
    // Do not display taxes with a 0 amount, unless it's the only tax
    if (taxAmount > 0 || pageData.tax_info.length === 1) {
      // Create tax element
      const taxElement = document.createElement('div');
      taxElement.className = 'cart-tax-item';
      taxElement.innerHTML = `
        <span>${taxName}:</span>
        <span>${formatPrice(taxAmount)}</span>
      `;
      
      cartTaxesContainer.appendChild(taxElement);
      hasTaxes = true;
    }
  });
  
  // Render tax container visibility
  cartTaxesContainer.style.display = hasTaxes ? 'block' : 'none';
  
  // Update parent container display
  if (cartTaxDetails) {
    cartTaxDetails.style.display = (hasTaxes && totalTaxAmount > 0) ? 'block' : 'none';
  }
}

// Function to add event listeners to cart buttons
function addCartButtonEvents() {
  // Quantity buttons
  const qtyButtons = document.querySelectorAll('.cart-btn, .qty-btn');
  qtyButtons.forEach(button => {
    button.addEventListener('click', handleQuantityChange);
  });

  // Buttons for removing items
  const removeButtons = document.querySelectorAll('.remove-cart-item, .remove-item');
  removeButtons.forEach(button => {
    button.addEventListener('click', handleRemoveItem);
  });
}

// Function to initialize add to cart buttons
function initAddToCartButtons() {
  // Select all add to cart buttons
  const addToCartButtons = document.querySelectorAll('.btn-add-to-cart:not(.is-gift-card), .btn-add-to-cart-list:not(.go-to-cart-grid)');

  // Add event listeners to each button
  addToCartButtons.forEach(button => {
    button.addEventListener('click', handleAddToCart);
  });
}

// Function to handle add to cart button click
function handleAddToCart(e) {
  e.preventDefault(); // Prevent default button behavior
  
  const button = e.currentTarget;
  
  // Get product information
  const itemCode = button.dataset.itemCode || button.getAttribute('data-item-code');
  
  // Find quantity in nearby input (item-qty)
  let qty = 1;
  const qtyInput = button.closest('.mb-4')?.querySelector('.item-qty') || 
                  document.querySelector(`.item-qty[data-item-code="${itemCode}"]`);
  
  if (qtyInput) {
    qty = parseInt(qtyInput.value) || 1;
  } else {
    // Fallback on data attributes if input is not found
    qty = parseInt(button.dataset.qty || button.getAttribute('data-qty') || 1);
  }
  
  // Get other available information (if present in attributes or nearby DOM)
  const itemName = button.dataset.itemName || '';
  const itemImage = button.dataset.itemImage || '';
  
  if (!itemCode) {
    return;
  }
  
  // Disable button and show loading indicator
  const originalText = button.innerHTML;
  button.disabled = true;
  button.classList.add('adding');
  button.innerHTML = `<span class="adding-text">` + __("Adding...") + `</span>`;
  
  // Add pulsing animation
  button.style.animation = 'pulse 1s infinite';
  
  // Call API to add item to cart  
  frappe.call({
    method: 'webshop.webshop.utils.cart_helpers.update_cart',
    args: {
      item_code: itemCode,
      qty: qty,
      additional_notes: '',
      with_items: 1,
      add_qty: true // Add to existing quantity
    },
    freeze: false,
    callback: function(r) {
      if (r.message && r.message.success !== false) {
        // Success animation
        button.classList.remove('adding');
        button.classList.add('added');
        button.innerHTML = `<span class="added-text">✓ ` + __("Added") + `</span>`;
        button.style.animation = 'none';
        button.style.backgroundColor = '#28a745';
        button.style.borderColor = '#28a745';
        button.style.color = 'white';
        
        // Update cart badge with animation
        refreshCartCount(r.message, qty);
        
        // Update cart content with new item
        updateCartWithNewItem(r.message, itemCode, itemName, itemImage, qty);
        
        // Force a direct update of the quantity elements for this product
        setTimeout(() => {          
          // Get final quantity and image from server response
          let serverQty = qty; // Default value
          let serverImage = itemImage; // Image par défaut
          
          if (r.message.items && Array.isArray(r.message.items)) {
            const item = r.message.items.find(i => i.item_code === itemCode);
            if (item) {
              // Get quantity from server response
              if (item.qty) {
                serverQty = parseInt(item.qty);
              }
              
              // Get image from server response
              if (item.website_image || item.thumbnail) {
                serverImage = item.website_image || item.thumbnail;
                
                // Update all images of this item in the cart
                const imgElements = document.querySelectorAll(`[data-item-code="${itemCode}"] .cart-item-image img`);
                if (imgElements.length > 0) {
                  imgElements.forEach(img => {
                    img.src = serverImage;
                    img.setAttribute('onerror', "this.onerror=null; this.parentNode.innerHTML='<div class=\\'item-abbr\\'>" + (item.item_name ? item.item_name.split(' ').map(w => w[0]).join('').toUpperCase() : '') + "</div>';");
                  });
                } else {
                  // If no image element, rebuild the image container
                  const imageContainers = document.querySelectorAll(`[data-item-code="${itemCode}"] .cart-item-image`);
                  imageContainers.forEach(container => {
                    container.innerHTML = `<img src="${serverImage}" alt="${item.item_name || ''}" onerror="this.onerror=null; this.parentNode.innerHTML='<div class=\\'item-abbr\\'>${item.item_name ? item.item_name.split(' ').map(w => w[0]).join('').toUpperCase() : ''}</div>';">`;
                  });
                }
              }
            }
          }
          
          // Force a direct update of the quantity elements for this product
          forceUpdateQuantityElement(itemCode, serverQty);
        }, 1000);
        
        // Display a floating mini cart (now with local data)
        showMiniCartNotification(itemCode, qty, itemName, itemImage);
        
        // Restore the button after a delay
        setTimeout(() => {
          button.innerHTML = originalText;
          button.disabled = false;
          button.classList.remove('added');
          button.style.backgroundColor = '';
          button.style.borderColor = '';
          button.style.color = '';
        }, 2000);
      } else {        
        // Error animation
        button.classList.remove('adding');
        button.classList.add('error');
        button.innerHTML = `<span class="error-text">` + __("Error") + `</span>`;
        button.style.animation = 'none';
        button.style.backgroundColor = '#dc3545';
        button.style.borderColor = '#dc3545';
        button.style.color = 'white';
        
        // Restore the button after a delay
        setTimeout(() => {
          button.innerHTML = originalText;
          button.disabled = false;
          button.classList.remove('error');
          button.style.backgroundColor = '';
          button.style.borderColor = '';
          button.style.color = '';
        }, 2000);
      }
    },
    error: function(err) {
      console.error('Error adding to cart:', err);
      
      // Error animation
      button.classList.remove('adding');
      button.classList.add('error');
      button.innerHTML = `<span class="error-text">` + __("Error") + `</span>`;
      button.style.animation = 'none';
      button.style.backgroundColor = '#dc3545';
      button.style.borderColor = '#dc3545';
      button.style.color = 'white';
      
      // Restore the button after a delay
      setTimeout(() => {
        button.innerHTML = originalText;
        button.disabled = false;
        button.classList.remove('error');
        button.style.backgroundColor = '';
        button.style.borderColor = '';
        button.style.color = '';
      }, 2000);
    }
  });
}

// Update the number of items in the cart based on the response
function refreshCartCount(response, qty = 0) {
  // Try to extract the number of items in the cart
  let itemCount = 0;
  
  if (response.total_qty !== undefined) {
    itemCount = response.total_qty;
  } else if (response.doc && response.doc.total_qty !== undefined) {
    itemCount = response.doc.total_qty;
  } else if (response.items && Array.isArray(response.items)) {
    // Calculate the sum of quantities
    itemCount = response.items.reduce((total, item) => total + (parseInt(item.qty) || 0), 0);
  }
  
  // If no quantity is found in the response but we have a quantity provided
  // and pageData contains a value for cart_items_count, add the new quantity
  if (itemCount === 0 && qty > 0 && typeof pageData !== 'undefined' && pageData.cart_items_count > 0) {
    itemCount = pageData.cart_items_count + qty;
  }
  
  // Update the badge of the cart
  if (cartBadge) {
    if (itemCount > 0) {
      cartBadge.textContent = itemCount;
      cartBadge.style.display = 'flex';
      
      // Animate the badge
      cartBadge.classList.add('updated');
      setTimeout(() => cartBadge.classList.remove('updated'), 500);
    } else {
      cartBadge.style.display = 'none';
    }
  }
  
  // Update pageData (global variable used for the cart)
  if (typeof pageData !== 'undefined') {
    pageData.cart_items_count = itemCount;
    
    // If we have additional information, update it too
    if (response.grand_total !== undefined) {
      pageData.cart_total = response.grand_total;
    } else if (response.doc && response.doc.grand_total !== undefined) {
      pageData.cart_total = response.doc.grand_total;
    }
  }
}

// Function to update the cart content with the new item
function updateCartWithNewItem(response, itemCode, itemName, itemImage, qtyToAdd = 0) {
  // If the cart is not open or the container does not exist, do nothing
  if (!cartItemsContainer) return;
  
  // Try to extract the new item data from the response
  let newItem = null;
  let currentQty = 0;
  let price = 0;
  let brand = '';
  let updatedItemName = itemName || '';
  let updatedItemImage = itemImage || '';
  
  // Try to extract the new item data from the response
  if (response.doc && response.doc.items) {
    // Search in doc.items
    newItem = response.doc.items.find(item => item.item_code === itemCode);
    if (newItem) {
      currentQty = newItem.qty || 0;
      price = newItem.rate || 0;
      brand = newItem.brand || '';
      // Update name and image if available
      updatedItemName = newItem.item_name || updatedItemName;
      updatedItemImage = newItem.website_image || newItem.thumbnail || updatedItemImage;
    }
  } else if (Array.isArray(response.items)) {
    // Search in the items array
    newItem = response.items.find(item => item.item_code === itemCode);
    if (newItem) {
      currentQty = newItem.qty || 0;
      price = newItem.rate || 0;
      brand = newItem.brand || '';
      // Update name and image if available
      updatedItemName = newItem.item_name || updatedItemName;
      updatedItemImage = newItem.website_image || newItem.thumbnail || updatedItemImage;
    }
  }
  
  // If the data is available in other parts of the response
  if (response.cart_info && Array.isArray(response.cart_info.items)) {
    // Search in cart_info.items
    const cartItem = response.cart_info.items.find(item => item.item_code === itemCode);
    if (cartItem) {
      updatedItemName = cartItem.item_name || updatedItemName;
      updatedItemImage = cartItem.website_image || cartItem.thumbnail || updatedItemImage;
    }
  }
  
  // Search all possible paths for the correct quantity
  if (!newItem || currentQty === 0) {    
    // 1. Check in the main structure of the response
    if (response.qty !== undefined && response.item_code === itemCode) {
      currentQty = parseInt(response.qty);
    }
    
    // 2. Check in the items array
    if (Array.isArray(response.items)) {
      const item = response.items.find(item => item.item_code === itemCode);
      if (item && item.qty !== undefined) {
        currentQty = parseInt(item.qty);
      }
    }
    
    // 3. Check in response.doc.items
    if (response.doc && Array.isArray(response.doc.items)) {
      const docItem = response.doc.items.find(item => item.item_code === itemCode);
      if (docItem && docItem.qty !== undefined) {
        currentQty = parseInt(docItem.qty);
      }
    }
    
    // 4. Check in response.message (standard Frappe API response structure)
    if (response.message) {
      // 4.1 Check if the quantity is directly in message
      if (response.message.qty !== undefined && (response.message.item_code === itemCode || !response.message.item_code)) {
        currentQty = parseInt(response.message.qty);
      }
      
      // 4.2 Check in doc.items
      if (response.message.doc && Array.isArray(response.message.doc.items)) {
        const docItem = response.message.doc.items.find(item => item.item_code === itemCode);
        if (docItem && docItem.qty !== undefined) {
          currentQty = parseInt(docItem.qty);
        }
      }
      
      // 4.3 Check in items
      if (Array.isArray(response.message.items)) {
        const messageItem = response.message.items.find(item => item.item_code === itemCode);
        if (messageItem && messageItem.qty !== undefined) {
          currentQty = parseInt(messageItem.qty);
        }
      }
    }
    
    // 5. Use the quantity provided in the parameter if everything fails
    if (currentQty === 0) {
      currentQty = qtyToAdd > 0 ? qtyToAdd : 1; // Use qtyToAdd if available, otherwise 1
    }
  }
  
  // If no quantity was found, try to deduce it from the interface
  if (currentQty === 0) {
    const existingQtyElement = cartItemsContainer.querySelector(`[data-item-code="${itemCode}"] .qty-value`);
    if (existingQtyElement) {
      const oldQty = parseInt(existingQtyElement.textContent, 10) || 0;
      // If a quantity to add is specified, use it, otherwise add 1
      currentQty = oldQty + (qtyToAdd > 0 ? qtyToAdd : 1);
    } else {
      // If it's a new item, use the quantity provided or 1 by default
      currentQty = qtyToAdd > 0 ? qtyToAdd : 1;
    }
  }
  
  // Check if the item already exists in the cart
  let existingItem = cartItemsContainer.querySelector(`[data-item-code="${itemCode}"]`);
  
  if (existingItem) {
    // If the item exists, update its quantity
    const qtyElement = existingItem.querySelector('.qty-value');
    if (qtyElement) {
      // Debug to see the current and new quantity
      const oldQty = parseInt(qtyElement.textContent, 10) || 0;
      
      // If the server response contains the items, use this quantity directly
      if (response.items && Array.isArray(response.items)) {
        const serverItem = response.items.find(item => item.item_code === itemCode);
        if (serverItem && serverItem.qty) {
          currentQty = parseInt(serverItem.qty);
        }
      }
      
      // Force the server quantity (more reliable) or add if specified
      if (qtyToAdd > 0 && (currentQty === oldQty || currentQty === 0)) {
        // If the server returns the same quantity or zero, add the new quantity
        const newQty = oldQty + qtyToAdd;
        currentQty = newQty;
      }
      
      // Call the force update function
      forceUpdateQuantityElement(itemCode, currentQty);
      
      // Direct HTML manipulation
      const parentElement = qtyElement.parentNode;
      const parentHTML = parentElement.innerHTML;
      // Replace directly in the HTML the value between the span tags
      const updatedHTML = parentHTML.replace(
        /<span\s+class="qty-value"[^>]*>\s*(\d+)\s*<\/span>/g, 
        `<span class="qty-value">${currentQty}</span>`
      );
      // Apply the new HTML
      parentElement.innerHTML = updatedHTML;
      
      // Method 2: Create a new element and replace the old one with force
      try {
        // Ensure the element is still valid after the first method
        const refreshedQtyElement = existingItem.querySelector('.qty-value');
        if (refreshedQtyElement) {
          // Forcer la valeur avec innerHTML, innerText et textContent
          refreshedQtyElement.innerHTML = currentQty.toString();
          refreshedQtyElement.innerText = currentQty.toString();
          refreshedQtyElement.textContent = currentQty.toString();
          
          // Add a data attribute to ensure the value is visible
          refreshedQtyElement.setAttribute('data-qty', currentQty.toString());
        }
      } catch (err) {
        console.error("Error updating DOM:", err);
      }
      
      // Method 3: Update all .qty-value elements in the item
      try {
        // Search for all .qty-value elements in this item
        const allQtyElements = existingItem.querySelectorAll('.qty-value');
        allQtyElements.forEach(el => {
          el.innerHTML = currentQty.toString();
          el.innerText = currentQty.toString();
          el.textContent = currentQty.toString();
        });
      } catch (err) {
        console.error("Error updating fallback:", err);
      }
            
      // Effect of update
      existingItem.classList.add('updating-ripple');
      setTimeout(() => {
        existingItem.classList.remove('updating-ripple');
        
        // Add a green flash to indicate successful update
        existingItem.style.transition = 'background-color 0.5s ease';
        existingItem.style.backgroundColor = 'rgba(40, 167, 69, 0.1)';
        
        // Method 4: Verify if DOM update was successful
        const finalCheckElement = existingItem.querySelector('.qty-value');
        if (finalCheckElement && parseInt(finalCheckElement.textContent) !== currentQty) {
          // Last resort: Force JavaScript to update the DOM
          forceUpdateQuantityElement(itemCode, currentQty);
          
          // If even the force update fails, refresh the cart completely
          setTimeout(() => {
            const finalFinalCheck = existingItem.querySelector('.qty-value');
            if (finalFinalCheck && parseInt(finalFinalCheck.textContent) !== currentQty) {
              // Force render = true to ignore the isRefreshing lock
              refreshCart(true);
            }
          }, 1000);
        }
        
        setTimeout(() => {
          existingItem.style.backgroundColor = '';
        }, 800);
      }, 1500);
      
      // Update the price if necessary
      if (price > 0) {
        const priceElement = existingItem.querySelector('.cart-item-price');
        if (priceElement) {
          priceElement.textContent = formatPrice(price);
        }
      }
    }
  } else {
    // Hide the "empty cart" message if present
    if (emptyCart) {
      emptyCart.style.display = 'none';
    }
    
    // Ensure the cart container is visible
    cartItemsContainer.style.display = 'block';
    
    // Create the HTML element for the new item
    const itemElement = document.createElement('div');
    itemElement.className = 'cart-item';
    itemElement.setAttribute('data-item-code', itemCode);
    
    // Generate abbreviation if necessary
    const abbr = updatedItemName ? updatedItemName.split(' ').map(word => word[0]).join('').toUpperCase() : '';
    
    // Find image from response if available
    let imageUrl = updatedItemImage;
    
    // Find image in server data if available
    if (response.items && Array.isArray(response.items)) {
      const serverItem = response.items.find(item => item.item_code === itemCode);
      if (serverItem && (serverItem.website_image || serverItem.thumbnail)) {
        imageUrl = serverItem.website_image || serverItem.thumbnail;
      }
    }
    
    // Add HTML for the item
    itemElement.innerHTML = `
      <div class="cart-item-image">
        ${imageUrl ? 
          `<img src="${imageUrl}" alt="${updatedItemName}" onerror="this.onerror=null; this.parentNode.innerHTML='<div class=\'item-abbr\'>${abbr}</div>';" />` : 
          `<div class="item-abbr">${abbr}</div>`}
      </div>
      <div class="cart-item-details">
        ${brand ? `<div class="cart-item-brand">${brand}</div>` : ''}
        <div class="cart-item-name">
          ${response.items && response.items.find(item => item.item_code === itemCode)?.route ? 
            `<a href="/${response.items.find(item => item.item_code === itemCode).route}" class="item-link">${updatedItemName}</a>` : 
            updatedItemName}
        </div>
        <div class="cart-item-price">${formatPrice(price)}</div>
        <div class="cart-item-quantity">
          <button class="qty-btn minus" data-item-code="${itemCode}" data-action="decrease">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="currentColor" d="M5 11h14v2H5z"/></svg>
          </button>
          <span class="qty-value">${currentQty}</span>
          <button class="qty-btn plus" data-item-code="${itemCode}" data-action="increase">
            <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"><path fill="currentColor" d="M19 11h-6V5h-2v6H5v2h6v6h2v-6h6z"/></svg>
          </button>
        </div>
      </div>
      <button class="remove-item" data-item-code="${itemCode}">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><path fill="currentColor" d="M19 6.41L17.59 5L12 10.59L6.41 5L5 6.41L10.59 12L5 17.59L6.41 19L12 13.41L17.59 19L19 17.59L13.41 12L19 6.41z"/></svg>
      </button>
    `;
    
    // Add element to container
    cartItemsContainer.appendChild(itemElement);
    
    // Add event listeners to buttons
    const qtyButtons = itemElement.querySelectorAll('.qty-btn');
    qtyButtons.forEach(button => {
      button.addEventListener('click', handleQuantityChange);
    });
    
    const removeButton = itemElement.querySelector('.remove-item');
    if (removeButton) {
      removeButton.addEventListener('click', handleRemoveItem);
    }
    
    // Add an entry animation
    itemElement.style.animationDuration = '0.5s';
    
    // Show the cart footer
    if (cartFooter) {
      cartFooter.style.display = 'block';
    }
  }
  
  // Update page data
  pageData.cart_items_count = response.total_qty || currentQty;
  if (response.grand_total !== undefined) {
    pageData.cart_total = response.grand_total;
  }
  
  // Update cart totals and taxes
  updateCartTotals(response);
}

// Function to open cart with highlight
function openCartWithHighlight(itemCode) {
  // Open the cart
  openCart();
  
  // Then highlight the added item
  if (itemCode && cartItemsContainer) {
    setTimeout(() => {
      const addedItem = cartItemsContainer.querySelector(`[data-item-code="${itemCode}"]`);
      if (addedItem) {
        // Scroll to the added item
        addedItem.scrollIntoView({ behavior: 'smooth', block: 'center' });
        
        // Add a highlight effect
        addedItem.style.transition = 'background-color 1s ease';
        addedItem.style.backgroundColor = 'rgba(40, 167, 69, 0.1)';
        setTimeout(() => {
          addedItem.style.backgroundColor = '';
        }, 2000);
      }
    }, 300);
  }
}

// Function to show mini cart notification
function showMiniCartNotification(itemCode, qty, itemName, itemImage) {
  // Check if notification already exists
  let notification = document.getElementById('cart-notification');
  
  // Create notification if it doesn't exist
  if (!notification) {
    notification = document.createElement('div');
    notification.id = 'cart-notification';
    notification.style.position = 'fixed';
    notification.style.top = '20px';
    notification.style.right = '20px';
    notification.style.backgroundColor = 'white';
    notification.style.boxShadow = '0 2px 10px rgba(0, 0, 0, 0.2)';
    notification.style.borderRadius = '4px';
    notification.style.padding = '15px';
    notification.style.zIndex = '1100';
    notification.style.maxWidth = '300px';
    notification.style.transform = 'translateY(-20px)';
    notification.style.opacity = '0';
    notification.style.transition = 'all 0.3s ease';
    
    document.body.appendChild(notification);
  }
  
  // Get product information from page context if itemName is not provided
  if (!itemName) {
    frappe.call({
      method: "webshop.webshop.shopping_cart.product_info.get_website_item_name",
      args: { item_code: itemCode },
      callback: function(r) {
        let productName = r.message || "Item " + itemCode;
        displayNotificationContent(notification, itemCode, qty, productName, itemImage);
      }
    });
  } else {
    displayNotificationContent(notification, itemCode, qty, itemName, itemImage);
  }
}

// Helper function to display notification content
function displayNotificationContent(notification, itemCode, qty, itemName, itemImage) {
  const imageUrl = itemImage;
  
  // Update notification content
  notification.innerHTML = `
    <div style="display: flex; align-items: center;">
      <div style="width: 50px; height: 50px; margin-right: 10px; flex-shrink: 0; background-color: #f5f5f5; display: flex; justify-content: center; align-items: center; border-radius: 4px;">
        ${itemImage ? 
          `<img src="${imageUrl}" alt="${itemName}" style="width: 100%; height: 100%; object-fit: contain;">` : 
          `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="20" height="20" rx="2" ry="2"/><circle cx="12" cy="12" r="3"/></svg>`
        }
      </div>
      <div>
        <div style="font-weight: bold; margin-bottom: 5px;">${itemName || 'Product'}</div>
        <div style="font-size: 14px; color: #28a745;">✓ ${__('Added to cart')} (${qty})</div>
      </div>
      <div style="margin-left: auto; cursor: pointer;" onclick="document.getElementById('cart-notification').remove()">×</div>
    </div>
    <div style="margin-top: 10px; text-align: center;">
      <button onclick="openCartWithHighlight('${itemCode}'); document.getElementById('cart-notification').remove();" 
              style="background-color: #000; color: white; border: none; padding: 5px 10px; border-radius: 4px; cursor: pointer;">
        ${__("View Cart")}
      </button>
    </div>
  `;
  
  // Animate appearance
  setTimeout(() => {
    notification.style.transform = 'translateY(0)';
    notification.style.opacity = '1';
  }, 10);
  
  // Hide after 5 seconds
  setTimeout(() => {
    notification.style.transform = 'translateY(-20px)';
    notification.style.opacity = '0';
    
    // Remove after animation end
    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 300);
  }, 5000);
}

// Function to animate buttons
document.head.insertAdjacentHTML('beforeend', `
  <style>
    @keyframes pulse {
      0% { transform: scale(1); }
      50% { transform: scale(1.05); }
      100% { transform: scale(1); }
    }
    
    .btn-add-to-cart.adding, .btn-add-to-cart-list.adding {
      animation: pulse 1s infinite;
    }
    
    /* Force visual refresh */
    .qty-value {
      display: inline-block !important;
      min-width: 1em !important;
    }
    
    /* Animation for quantity update */
    @keyframes qty-update {
      0% { transform: scale(1); }
      50% { transform: scale(1.2); background-color: rgba(40, 167, 69, 0.2); }
      100% { transform: scale(1); }
    }
    
    .qty-updated {
      animation: qty-update 0.5s ease-in-out;
    }
    
    /* Style for links in cart */
    .cart-item-name a.item-link {
      color: inherit;
      text-decoration: none;
      transition: color 0.2s ease;
    }
    
    .cart-item-name a.item-link:hover {
      color: var(--primary-color, #4287f5);
      text-decoration: underline;
    }
  </style>
`);

// Function to force quantity update in the DOM
function forceUpdateQuantityElement(itemCode, newQty) {
  // Script to be executed directly in the DOM
  const script = document.createElement('script');
  script.textContent = `
    (function() {
      // Function to try multiple update methods
      function updateQtyElements() {
        // Find all quantity elements for this item
        const qtyElements = document.querySelectorAll('[data-item-code="${itemCode}"] .qty-value, .cart-item-quantity .qty-value');
        
        if (qtyElements.length > 0) {          
          qtyElements.forEach((el, index) => {
            try {
              // Store old value
              const oldValue = el.textContent || el.innerText;
              
              // Force update with all possible methods
              el.innerHTML = "${newQty}";
              el.innerText = "${newQty}";
              el.textContent = "${newQty}";
              el.setAttribute('data-qty', "${newQty}");
              
              // Add animation class
              el.classList.add('qty-updated');
              
              // Remove animation class after animation
              setTimeout(() => {
                el.classList.remove('qty-updated');
              }, 500);
            } catch(e) {
              console.error("Error updating element #" + index, e);
            }
          });
        } else {          
          // Try to find all qty-value elements
          const allQtyElements = document.querySelectorAll('.qty-value');
          
          // Update all quantity elements in the cart
          allQtyElements.forEach((el, index) => {
            const parent = el.closest('[data-item-code]');
            if (parent && parent.getAttribute('data-item-code') === "${itemCode}") {
              try {
                el.innerHTML = "${newQty}";
                el.innerText = "${newQty}";
                el.textContent = "${newQty}";
              } catch(e) {
                console.error("Error updating extended element #" + index, e);
              }
            }
          });
        }
      }
      
      // Execute immediately
      updateQtyElements();
      
      // Then retry after a short delay
      setTimeout(updateQtyElements, 100);
      
      // And again after a longer delay
      setTimeout(updateQtyElements, 500);
    })();
  `;
  
  // Add the script to the document and execute
  document.body.appendChild(script);
  
  // Clean up by removing the script after execution
  setTimeout(() => {
    document.body.removeChild(script);
  }, 1000);
}

// Initialize buttons on page load
document.addEventListener('DOMContentLoaded', function() {
  initAddToCartButtons();
  
  // Also reset on AJAX load (for catalog pages with filters)
  if (typeof $ !== 'undefined') {
    $(document).ajaxComplete(function() {
      setTimeout(initAddToCartButtons, 500);
    });
  }
});

// Initialize initial events

// Open cart
if (cartButton) {
  cartButton.addEventListener('click', function(e) {
    e.preventDefault();
    openCart();
  });
}

// Close cart with close button (×)
if (closeCartButton) {
  closeCartButton.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation(); // Prevent propagation to parent elements
    closeCart();
  });
}

// Close cart by clicking outside
if (cartOverlay) {
  cartOverlay.addEventListener('click', function(e) {
    if (e.target === cartOverlay) {
      closeCart();
    }
  });
}

// Prevent click propagation from the cart itself
if (sideCart) {
  sideCart.addEventListener('click', function(e) {
    e.stopPropagation(); // Prevent clicks inside the cart from closing the cart
  });
}

// Initialize cart interface
updateCartUI();