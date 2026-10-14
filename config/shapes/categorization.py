from ntuple_processor.utils import Selection


def build_categorization(regions):
    """{channel: {region: (cut, [Histogram, ...])}} -> {channel: [(Selection, [Histogram, ...]), ...]} as booked by produce_shapes."""
    return {
        channel: [(Selection(name=region, cuts=[(cut, "category_selection")]), histograms) for region, (cut, histograms) in channel_regions.items()]
        for channel, channel_regions in regions.items()
    }
