package domain

// UpdateStateRequest is the request body for POST /api/led.
type UpdateStateRequest struct {
	State string `json:"state" binding:"required"`
}
