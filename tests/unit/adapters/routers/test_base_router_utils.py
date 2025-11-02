from stacklion_api.adapters.routers.base_router import BaseRouter


def test_base_router_prefix_and_tags():
    r = BaseRouter(version="v9", resource="widgets", tags=["Widgets"])
    # APIRouter exposes the configured prefix/tags
    assert r.prefix == "/v9/widgets"
    assert "Widgets" in (r.tags or [])


def test_page_params_clamping_and_per_page_passthrough():
    # Clamp extremes: page < MIN -> MIN, page_size > MAX -> MAX
    pp = BaseRouter.page_params(page=0, page_size=10_000, per_page=None)
    assert pp.page == BaseRouter.MIN_PAGE
    assert pp.page_size == BaseRouter.MAX_PAGE_SIZE
    assert pp.offset == (pp.page - 1) * pp.page_size
    assert pp.limit == pp.page_size

    # per_page should be honored only when page_size is None
    pp2 = BaseRouter.page_params(page=None, page_size=None, per_page=25)
    assert pp2.page == BaseRouter.MIN_PAGE  # defaulted
    assert pp2.page_size == 25
