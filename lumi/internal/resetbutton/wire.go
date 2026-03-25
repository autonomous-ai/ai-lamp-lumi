package resetbutton

import (
	"github.com/google/wire"
)

// ProviderSet exposes reset button providers for Wire.
// ProvideServiceOptional returns *Service (nil when GPIO unavailable, e.g. dev machine).
var ProviderSet = wire.NewSet(
	ProvideServiceOptional,
)

// ProvideServiceOptional returns a Service when GPIO 23 is available; otherwise nil so server can still start.
func ProvideServiceOptional() *Service {
	s, err := ProvideService()
	if err != nil {
		return nil
	}
	return s
}
