function(doc) {
    if (doc.recommendations && doc.recommendations.length !== undefined) {
        emit(doc.recommendations.length, null);
    }
}