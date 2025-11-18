function(doc) {
    if (doc.total_engagements !== undefined) {
        emit(doc.total_engagements, null);
    }
}