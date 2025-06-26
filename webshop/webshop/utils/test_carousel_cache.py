import unittest
import frappe
from frappe.tests.utils import FrappeTestCase
from webshop.webshop.utils.carousel_cache import CarouselCacheManager
from webshop.webshop.utils.product_carousel_helper import get_carousel_items


class TestCarouselCache(FrappeTestCase):
    def setUp(self):
        """Set up test data."""
        self.cache_manager = CarouselCacheManager()
        # Clear any existing cache
        self.cache_manager.clear_cache()
        
    def tearDown(self):
        """Clean up after tests."""
        self.cache_manager.clear_cache()
    
    def test_cache_key_generation(self):
        """Test that cache keys are generated consistently."""
        params1 = {
            "item_group": "Electronics",
            "limit": 8,
            "sort_by": "creation"
        }
        params2 = {
            "limit": 8,
            "item_group": "Electronics", 
            "sort_by": "creation"
        }
        
        key1 = self.cache_manager.generate_cache_key(**params1)
        key2 = self.cache_manager.generate_cache_key(**params2)
        
        # Keys should be the same regardless of parameter order
        self.assertEqual(key1, key2)
        
        # Different parameters should generate different keys
        params3 = {
            "item_group": "Clothing",
            "limit": 8,
            "sort_by": "creation"
        }
        key3 = self.cache_manager.generate_cache_key(**params3)
        self.assertNotEqual(key1, key3)
    
    def test_cache_set_and_get(self):
        """Test setting and retrieving items from cache."""
        test_items = [
            {"name": "Item1", "price": 100},
            {"name": "Item2", "price": 200}
        ]
        
        cache_key = self.cache_manager.generate_cache_key(test="cache_test")
        
        # Set cache
        self.cache_manager.set_cache(cache_key, test_items, ttl=60)
        
        # Get from cache
        cached_items = self.cache_manager.get_from_cache(cache_key)
        
        self.assertIsNotNone(cached_items)
        self.assertEqual(len(cached_items), 2)
        self.assertEqual(cached_items[0]["name"], "Item1")
    
    def test_cache_clear(self):
        """Test clearing cache."""
        # Set some test data
        cache_key = self.cache_manager.generate_cache_key(test="clear_test")
        self.cache_manager.set_cache(cache_key, [{"test": "data"}], ttl=60)
        
        # Verify it's cached
        self.assertIsNotNone(self.cache_manager.get_from_cache(cache_key))
        
        # Clear cache
        self.cache_manager.clear_cache()
        
        # Verify it's cleared
        self.assertIsNone(self.cache_manager.get_from_cache(cache_key))
    
    def test_get_carousel_items_with_cache(self):
        """Test get_carousel_items function with cache enabled."""
        # First call - should hit database
        items1 = get_carousel_items(
            limit=5,
            sort_by="creation",
            use_cache=True,
            cache_ttl=300
        )
        
        # Second call with same parameters - should hit cache
        items2 = get_carousel_items(
            limit=5,
            sort_by="creation",
            use_cache=True,
            cache_ttl=300
        )
        
        # Results should be identical
        self.assertEqual(len(items1), len(items2))
        if items1:  # Only test if we have items
            self.assertEqual(items1[0], items2[0])
    
    def test_get_carousel_items_without_cache(self):
        """Test that cache can be disabled."""
        # Call without cache
        items = get_carousel_items(
            limit=5,
            sort_by="creation",
            use_cache=False  # Cache explicitly disabled
        )
        
        # Generate the key that would have been used
        cache_params = {
            "item_group": None,
            "only_promotions": False,
            "limit": 5,
            "sort_by": "creation",
            "sort_order": "desc",
            "brand": None,
            "exclude_items": None,
            "search_term": None
        }
        cache_key = self.cache_manager.generate_cache_key(**cache_params)
        
        # Verify nothing was cached
        self.assertIsNone(self.cache_manager.get_from_cache(cache_key))
    
    def test_cache_with_different_parameters(self):
        """Test that different parameters create different cache entries."""
        # First query
        items1 = get_carousel_items(
            limit=5,
            sort_by="creation",
            use_cache=True
        )
        
        # Second query with different parameters
        items2 = get_carousel_items(
            limit=10,  # Different limit
            sort_by="creation",
            use_cache=True
        )
        
        # Should potentially have different number of items
        # (unless there are less than 5 items total)
        if len(items1) >= 5 and len(items2) >= 10:
            self.assertNotEqual(len(items1), len(items2))