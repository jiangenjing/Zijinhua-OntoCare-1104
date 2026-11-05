from .reference_agent import SourceActionAgent
from .customer_workflow import WorkflowAgentMixin
class CustomerWorkflowAgent(WorkflowAgentMixin,SourceActionAgent):
    pass
