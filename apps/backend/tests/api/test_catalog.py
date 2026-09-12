"""Catalog products/price-books routes are live (not 501 stubs)."""
from __future__ import annotations


def test_catalog_products_requires_auth(client) -> None:
    response = client.get("/api/catalog/products")
    assert response.status_code == 401


def test_price_books_requires_auth(client) -> None:
    response = client.get("/api/price-books")
    assert response.status_code == 401


def test_catalog_and_price_books_routes_registered(app) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/catalog/products" in paths
    assert "/api/price-books" in paths
