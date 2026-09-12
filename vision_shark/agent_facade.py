from __future__ import annotations
from typing import Callable

class ReadOnlyAgentFacade:
    """Bounded assistant surface. No mutation, diagnostics writes, transmit or actuation tools exist here."""
    ALLOWED=('status','readiness','recordings','knowledge')
    def __init__(self,providers:dict[str,Callable[[],object]]):
        unknown=set(providers)-set(self.ALLOWED)
        if unknown:raise ValueError('unapproved agent providers: '+','.join(sorted(unknown)))
        self.providers=dict(providers)
    def capabilities(self):return {'tools':sorted(self.providers),'mutating_tools':[],'vehicle_tx':False,'live_actuation':False}
    def call(self,name):
        if name not in self.providers:raise PermissionError('tool unavailable to read-only agent')
        return self.providers[name]()
