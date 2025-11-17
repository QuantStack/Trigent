function(doc) {
    if (doc.pulled_date) {
        emit(doc.pulled_date, null);
    }
}