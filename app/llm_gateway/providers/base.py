from abc import ABC,abstractmethod
class BaseProvider(ABC):
    @abstractmethod
    def complete(self,request,model):...
