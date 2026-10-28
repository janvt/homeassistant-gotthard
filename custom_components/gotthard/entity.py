"""What the Gotthard's entities share."""


class StableObjectId:
    """An entity whose id comes from a fixed key, not from its name: the
    Axenstrasse's are named "Axenstrasse (A4)", and their ids stay
    `…_axenstrasse…`, as dashboards use them."""

    _object_id: str | None = None

    @property
    def suggested_object_id(self) -> str | None:
        return self._object_id or super().suggested_object_id
