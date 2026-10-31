def attach(*args,**kwargs):
    from .comparison import attach as _attach
    return _attach(*args,**kwargs)
def summarize(*args,**kwargs):
    from .observability import summarize as _summarize
    return _summarize(*args,**kwargs)
__all__=["attach","summarize"]
