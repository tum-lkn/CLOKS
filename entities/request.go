package entities

// PodPhase represents the lifecycle phase of a Pod.
type RequestStatus string

const (
	RequestArrived   RequestStatus = "Arrived"
	RequestServing   RequestStatus = "Serving"
	RequestCompleted RequestStatus = "Completed"
	RequestTimeout   RequestStatus = "Timeout"
	RequestError     RequestStatus = "Error"
)

// Request represents a network request
type Request struct {
	ID          int
	status      RequestStatus // "arrived", "processing", "departed", etc.
	ServiceName string
	ProfileName string
	Task        *Task

	// Multi-tier support
	originRequest           *Request   // The first request where this whole request chain originated
	downstreamRequest       *Request   // Downstream (parent) request (nil for root requests)
	upstreamRequests        []*Request // Upstream (child) requests of this Request
	Depth                   int        // Depth in the call chain (0 for root, 1 for first upstream, etc.)
	NextUpstreamIdx         int        // Index of the next upstream config to evaluate for this request (for downstream requests)
	triggeredUpstreamCfgIdx int        // Index of the upstream config that triggered this request (for upstream requests)

	// TIMES
	ProcessingTime   float64 // Total processing time for this request (including upstream calls)
	TimeLBArrival    float64
	TimePodArrival   float64
	TimePodDeparture float64
	TimeLBDeparture  float64
}

// NewRequest creates a new Request
func NewRequest(serviceName, profileName string, processingTime float64) *Request {
	return &Request{
		ID:                      0,
		status:                  RequestArrived,
		ServiceName:             serviceName,
		ProfileName:             profileName,
		Task:                    nil,
		NextUpstreamIdx:         0,
		triggeredUpstreamCfgIdx: -1,

		ProcessingTime: processingTime,
	}
}

func (req *Request) TimedOut() bool { return req.status == RequestTimeout }
func (req *Request) Errored() bool  { return req.status == RequestError }

func (req *Request) Status() RequestStatus          { return req.status }
func (req *Request) SetStatus(status RequestStatus) { req.status = status }

func (req *Request) OriginRequest() *Request          { return req.originRequest }
func (req *Request) SetOriginRequest(origin *Request) { req.originRequest = origin }

func (req *Request) DownstreamRequest() *Request              { return req.downstreamRequest }
func (req *Request) SetDownstreamRequest(downstream *Request) { req.downstreamRequest = downstream }

func (req *Request) UpstreamRequests() []*Request {
	return append([]*Request{}, req.upstreamRequests...)
}

func (req *Request) AppendUpstreamRequest(upstream *Request) {
	if upstream == nil {
		return
	}
	req.upstreamRequests = append(req.upstreamRequests, upstream)
}

func (req *Request) TriggeredUpstreamCfgIdx() int {
	return req.triggeredUpstreamCfgIdx
}

func (req *Request) SetTriggeredUpstreamCfgIdx(idx int) {
	req.triggeredUpstreamCfgIdx = idx
}
