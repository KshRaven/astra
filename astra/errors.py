class PanelError(Exception):
    """Expected, user-facing error. Returned to clients as {"error": message}."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status
